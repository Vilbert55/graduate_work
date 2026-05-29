"""APScheduler + LISTEN/NOTIFY движок alerting.

Что делает на каждый тик правила:
  1) Перечитывает t_rules, синхронизирует набор jobs с активными правилами.
  2) По cron-расписанию вызывает services.executor.execute_rule, который
     открывает StarRocks-сессию, выполняет SQL, и через
     notifications.adm_create_task создаёт задачу на рассылку.

Параллельно: фоновая корутина слушает Postgres LISTEN-канал
'alerting_trigger' — adm_trigger_rule/adm_dry_run_rule SQL-функции шлют
NOTIFY с полезной нагрузкой 'trigger:{rule_id}:{run_id}' или
'dryrun:{rule_id}:{run_id}'. Движок подхватывает и исполняет тот же
executor.execute_rule с подготовленным run_id.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from contextlib import suppress

import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.core.config import settings
from src.db.postgres import async_session_maker
from src.models.entity import Rule
from src.services.executor import RuleNotFoundError, execute_rule


logger = logging.getLogger(__name__)
NOTIFY_CHANNEL = "alerting_trigger"


def _job_id(rule_id: uuid.UUID) -> str:
    return f"rule:{rule_id}"


async def _tick(rule_id: uuid.UUID, rule_code: str) -> None:
    """Job-функция, вызываемая APScheduler по cron каждого правила."""
    logger.info("engine tick", extra={"rule_id": str(rule_id), "rule_code": rule_code})
    try:
        await execute_rule(rule_id)
    except RuleNotFoundError:
        logger.warning("rule disappeared between sync and tick", extra={"rule_id": str(rule_id)})


async def _sync_jobs(scheduler: AsyncIOScheduler) -> None:
    """Перечитать t_rules и синхронизировать набор APScheduler jobs."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(Rule).where(Rule.is_enabled.is_(True), Rule.is_deleted.is_(False)),
        )
        rules: list[Rule] = list(result.scalars().all())

    active_ids: set[str] = {_job_id(r.id) for r in rules}
    scheduled_ids: set[str] = {j.id for j in scheduler.get_jobs()}

    for job_id in scheduled_ids - active_ids:
        scheduler.remove_job(job_id)
        logger.info("removed job", extra={"job_id": job_id})

    for rule in rules:
        job_id = _job_id(rule.id)
        try:
            trigger = CronTrigger.from_crontab(rule.cron_expression)
        except ValueError:
            logger.warning(
                "invalid cron — skipping",
                extra={"rule_id": str(rule.id), "cron": rule.cron_expression},
            )
            continue

        if job_id in scheduled_ids:
            scheduler.reschedule_job(job_id, trigger=trigger)
        else:
            scheduler.add_job(
                _tick,
                trigger=trigger,
                args=(rule.id, rule.code),
                id=job_id,
                name=f"alerting_rule_{rule.code}",
                replace_existing=True,
                misfire_grace_time=60,
                coalesce=True,
            )
            logger.info(
                "added job",
                extra={"job_id": job_id, "cron": rule.cron_expression},
            )


def _asyncpg_dsn() -> str:
    """asyncpg хочет 'postgresql://' (без +asyncpg)."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _handle_trigger_payload(payload: str) -> None:
    """Parsing 'trigger:{rule_id}:{run_id}' или 'dryrun:{rule_id}:{run_id}'."""
    try:
        kind, rule_raw, run_raw = payload.split(":", 2)
        rule_id = uuid.UUID(rule_raw)
        run_id = uuid.UUID(run_raw)
    except ValueError:
        logger.warning("invalid notify payload", extra={"payload": payload})
        return

    dry_run = kind == "dryrun"
    try:
        await execute_rule(rule_id, run_id=run_id, dry_run=dry_run)
    except RuleNotFoundError:
        logger.warning("manual trigger: rule not found", extra={"rule_id": str(rule_id)})


async def _listen_for_triggers(stop_event: asyncio.Event) -> None:
    """LISTEN на канале 'alerting_trigger', с авто-переподключением."""
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_conn, _pid, _channel, payload):
        queue.put_nowait(payload)

    while not stop_event.is_set():
        try:
            conn = await asyncpg.connect(dsn=_asyncpg_dsn())
            await conn.add_listener(NOTIFY_CHANNEL, _on_notify)
            logger.info("listening for triggers", extra={"channel": NOTIFY_CHANNEL})
            try:
                while not stop_event.is_set():
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
                    asyncio.create_task(_handle_trigger_payload(payload))  # noqa: RUF006
            finally:
                with suppress(Exception):
                    await conn.remove_listener(NOTIFY_CHANNEL, _on_notify)
                with suppress(Exception):
                    await conn.close()
        except Exception:  # noqa: BLE001 — переподключаемся
            if stop_event.is_set():
                return
            logger.exception("listener crashed — reconnect in 5s")
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=5)


async def run() -> None:
    """Главная точка движка."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    logger.info("alerting-engine started")

    await _sync_jobs(scheduler)

    stop_event = asyncio.Event()

    def _on_signal() -> None:
        logger.info("shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal)

    listener_task = asyncio.create_task(_listen_for_triggers(stop_event))

    try:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.rules_refresh_interval_sec)
            except asyncio.TimeoutError:
                await _sync_jobs(scheduler)
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.gather(listener_task, return_exceptions=True)
        logger.info("alerting-engine stopped")

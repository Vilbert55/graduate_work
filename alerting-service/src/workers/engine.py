"""APScheduler-движок: читает alerting.t_rules и ставит job на каждое правило.

На неделе 2 job-функция только структурированно логирует факт срабатывания.
На неделе 3 функция будет:
  1) открывать соединение с StarRocks под alert_reader,
  2) выполнять sql_query правила с тайм-аутом starrocks_query_timeout_sec,
  3) применять frequency_cap из t_dispatch_history,
  4) формировать idempotency_key 'alerting:{rule_id}:{run_id}',
  5) одной транзакцией писать t_runs / t_dispatch_history и вызывать
     notifications.adm_create_task(...).
"""
from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.core.config import settings
from src.db.postgres import async_session_maker
from src.models.entity import Rule


logger = logging.getLogger(__name__)


def _job_id(rule_id: UUID) -> str:
    return f"rule:{rule_id}"


async def _tick(rule_id: UUID, rule_code: str) -> None:
    """Job-функция для каждого правила. На неделе 2 — только лог."""
    logger.info(
        "engine tick: would execute rule",
        extra={"rule_id": str(rule_id), "rule_code": rule_code},
    )


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

    try:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.rules_refresh_interval_sec)
            except asyncio.TimeoutError:
                await _sync_jobs(scheduler)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("alerting-engine stopped")

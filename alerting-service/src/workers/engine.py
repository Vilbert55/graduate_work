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
from sqlalchemy import select, text

from src.core.config import settings
from src.db.postgres import async_session_maker
from src.models.entity import Rule
from src.services.executor import RuleNotFoundError, execute_rule


logger = logging.getLogger(__name__)
NOTIFY_CHANNEL = "alerting_trigger"  # Postgres-канал, по которому приходят ручные запуски


def _job_id(rule_id: uuid.UUID) -> str:
    """Стабильный id job-а в APScheduler по id правила (одно правило — один job)."""
    return f"rule:{rule_id}"


async def _tick(rule_id: uuid.UUID, rule_code: str) -> None:
    """Job-функция, вызываемая APScheduler по cron каждого правила."""
    logger.info("engine tick", extra={"rule_id": str(rule_id), "rule_code": rule_code})
    try:
        # Вся работа (SQL в StarRocks + создание задачи на рассылку) — внутри execute_rule.
        await execute_rule(rule_id)
    except RuleNotFoundError:
        # Правило успели удалить между синхронизацией jobs и срабатыванием — не страшно.
        logger.warning("rule disappeared between sync and tick", extra={"rule_id": str(rule_id)})


async def _sync_jobs(scheduler: AsyncIOScheduler) -> None:
    """Привести набор APScheduler jobs в соответствие с активными правилами в БД.

    Вызывается при старте и затем периодически — так включённые/выключенные/
    удалённые в БД правила подхватываются движком без перезапуска.
    """
    # 1. Берём из БД все правила, которые должны работать (включены и не удалены).
    async with async_session_maker() as session:
        result = await session.execute(
            select(Rule).where(Rule.is_enabled.is_(True), Rule.is_deleted.is_(False)),
        )
        rules: list[Rule] = list(result.scalars().all())

    # 2. Сравниваем "как должно быть" (из БД) с "как сейчас" (в планировщике).
    #    Учитываем только job-ы правил (id вида rule:*) — служебные job-ы вроде
    #    обслуживания партиций (maint:*) синхронизация не трогает.
    active_ids: set[str] = {_job_id(r.id) for r in rules}
    scheduled_ids: set[str] = {j.id for j in scheduler.get_jobs() if j.id.startswith("rule:")}

    # 3. Снимаем jobs правил, которых больше нет в выборке (выключили/удалили).
    for job_id in scheduled_ids - active_ids:
        scheduler.remove_job(job_id)
        logger.info("removed job", extra={"job_id": job_id})

    # 4. Для каждого активного правила заводим или обновляем его job.
    for rule in rules:
        job_id = _job_id(rule.id)
        try:
            # Разбираем cron-строку правила в триггер APScheduler.
            trigger = CronTrigger.from_crontab(rule.cron_expression)
        except ValueError:
            # Битый cron не валит весь движок — просто пропускаем это правило.
            logger.warning(
                "invalid cron — skipping",
                extra={"rule_id": str(rule.id), "cron": rule.cron_expression},
            )
            continue

        if job_id in scheduled_ids:
            # Job уже есть — могло смениться расписание, обновляем триггер.
            scheduler.reschedule_job(job_id, trigger=trigger)
        else:
            # Нового правила в планировщике ещё нет — добавляем job.
            scheduler.add_job(
                _tick,
                trigger=trigger,
                args=(rule.id, rule.code),       # что передать в _tick
                id=job_id,
                name=f"alerting_rule_{rule.code}",
                replace_existing=True,
                misfire_grace_time=60,           # опоздание job-а до 60с ещё допустимо
                coalesce=True,                   # копившиеся пропуски схлопнуть в один запуск
            )
            logger.info(
                "added job",
                extra={"job_id": job_id, "cron": rule.cron_expression},
            )


async def _handle_trigger_payload(payload: str) -> None:
    """Обработать одно NOTIFY-уведомление о ручном запуске правила.

    Пейлоад — строка 'trigger:{rule_id}:{run_id}' или 'dryrun:{rule_id}:{run_id}',
    которую сформировала SQL-функция alerting._enqueue_rule_run.
    """
    try:
        # Разбираем три части пейлоада: вид запуска и два UUID.
        kind, rule_raw, run_raw = payload.split(":", 2)
        rule_id = uuid.UUID(rule_raw)
        run_id = uuid.UUID(run_raw)
    except ValueError:
        # Мусор в канале — логируем и игнорируем, движок продолжает работать.
        logger.warning("invalid notify payload", extra={"payload": payload})
        return

    # 'dryrun' — посчитать аудиторию, но письма НЕ слать (тестовый прогон).
    dry_run = kind == "dryrun"
    try:
        # run_id уже создан SQL-функцией — переиспользуем его, новый не заводим.
        await execute_rule(rule_id, run_id=run_id, dry_run=dry_run)
    except RuleNotFoundError:
        logger.warning("manual trigger: rule not found", extra={"rule_id": str(rule_id)})


async def _listen_for_triggers(stop_event: asyncio.Event) -> None:
    """Слушать Postgres-канал 'alerting_trigger' до остановки, переподключаясь при обрыве."""

    # Колбэк asyncpg вызывается прямо в event-loop, поэтому сразу запускаем
    # обработку пейлоада отдельной задачей и не блокируем приём уведомлений.
    def _on_notify(_conn, _pid, _channel, payload):
        asyncio.create_task(_handle_trigger_payload(payload))  # noqa: RUF006

    # Внешний цикл = живучесть: если соединение оборвётся, переподключаемся.
    while not stop_event.is_set():
        try:
            conn = await asyncpg.connect(dsn=settings.asyncpg_dsn)
            await conn.add_listener(NOTIFY_CHANNEL, _on_notify)  # подписка на канал
            logger.info("listening for triggers", extra={"channel": NOTIFY_CHANNEL})
            try:
                await stop_event.wait()  # держим соединение живым до сигнала остановки
            finally:
                with suppress(Exception):
                    await conn.close()
        except Exception:  # соединение упало, ждём 5с и переподключаемся
            if stop_event.is_set():
                return
            logger.exception("listener crashed — reconnect in 5s")
            # Пауза перед реконнектом, но прерываемая сигналом остановки.
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=5)


async def _maintain_partitions() -> None:
    """Нарезать недельные партиции t_dispatch_history и подчистить старые (ФТ-8)."""
    async with async_session_maker() as session:
        await session.execute(
            text("SELECT alerting.maint_dispatch_partitions(:days)"),
            {"days": settings.dispatch_retention_days},
        )
        await session.commit()


async def _recover_interrupted_runs() -> None:
    """Дозавершить запуски, прерванные сбоем движка (НФТ-3).

    Берём t_runs со статусом 'running' старше recovery_grace_sec (dry-run
    исключаем — у него нет рассылки, которую можно «потерять») и повторяем
    execute_rule с тем же run_id. Атомарность фазы dispatch гарантирует, что
    повтор не создаст дублей: 'running' ⟺ ничего не закоммичено.
    """
    async with async_session_maker() as session:
        rows = (await session.execute(
            text(
                "SELECT id, rule_id FROM alerting.t_runs "
                "WHERE status = 'running' AND is_dry_run = FALSE "
                "  AND started_at < (now() AT TIME ZONE 'utc') - make_interval(secs => :grace)"
            ),
            {"grace": settings.recovery_grace_sec},
        )).all()

    for run_id, rule_id in rows:
        logger.info("recovering interrupted run", extra={"run_id": str(run_id), "rule_id": str(rule_id)})
        try:
            await execute_rule(rule_id, run_id=run_id)
        except RuleNotFoundError:
            # Правило успели удалить — закрываем осиротевший запуск как failed.
            async with async_session_maker() as session:
                await session.execute(
                    text("UPDATE alerting.t_runs SET status='failed', error='rule_deleted', "
                         "finished_at=(now() AT TIME ZONE 'utc') WHERE id = :rid"),
                    {"rid": run_id},
                )
                await session.commit()


async def run() -> None:
    """Точка входа: поднимает планировщик, слушатель и держит их до остановки."""
    # Планировщик гоняет правила по их cron (всё в UTC).
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.start()
    logger.info("alerting-engine started")

    # Обслуживание партиций истории отправок: сразу + раз в сутки в 00:05 UTC.
    await _maintain_partitions()
    scheduler.add_job(
        _maintain_partitions,
        trigger=CronTrigger.from_crontab("5 0 * * *"),
        id="maint:dispatch_partitions",
        name="maint_dispatch_partitions",
        replace_existing=True,
    )

    # Восстановление прерванных сбоем запусков (НФТ-3) — до планирования правил.
    await _recover_interrupted_runs()

    # Первичная загрузка правил из БД в планировщик.
    await _sync_jobs(scheduler)

    # Общий «выключатель»: его взводят по SIGINT/SIGTERM, на него смотрят оба цикла.
    stop_event = asyncio.Event()

    def _on_signal() -> None:
        logger.info("shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal)

    # Параллельная ветка: слушатель ручных запусков через LISTEN/NOTIFY.
    listener_task = asyncio.create_task(_listen_for_triggers(stop_event))

    try:
        # Основной цикл: раз в rules_refresh_interval_sec пересинхронизируем jobs.
        # wait_for с таймаутом = «спать интервал ИЛИ проснуться сразу на остановку».
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.rules_refresh_interval_sec)
            except TimeoutError:
                await _sync_jobs(scheduler)  # таймаут вышел — время пересинхронизироваться
    finally:
        # Корректное завершение: гасим планировщик и дожидаемся слушателя.
        scheduler.shutdown(wait=False)
        await asyncio.gather(listener_task, return_exceptions=True)
        logger.info("alerting-engine stopped")

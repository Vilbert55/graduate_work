"""Scheduler: создание notification_messages из заданий.

Цикл:
  1. SELECT FOR UPDATE SKIP LOCKED заданий, у которых is_enabled=TRUE
     и next_run_at <= NOW().
  2. Для каждого:
       - проверка end_at (истёк — disable);
       - раскрытие audience -> список user_ids;
       - батчевый запрос данных пользователей через AuthClient;
       - рендеринг шаблона Jinja2 (subject + body) для каждого user_id;
       - bulk INSERT в notification_messages (ON CONFLICT DO NOTHING
         по (task_id, user_id, run_at) — идемпотентность);
       - расчёт next_run_at через croniter (или disable для одноразового);
       - UPDATE задания: last_run_at, next_run_at.
     Всё в одной транзакции — крах в середине откатит изменения,
     при следующем тике задание возьмётся снова, и ON CONFLICT защитит от дубликатов.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from croniter import croniter
from sqlalchemy import text

from src.core.config import settings
from src.core.logging import setup_logging
from src.db.postgres import async_session_maker
from src.shared.auth_client import AuthClient, UserData
from src.shared.templating import render
from src.shared.worker_loop import install_shutdown_handlers, run_periodic


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskRow:
    id: UUID
    name: str
    template_id: UUID
    channel: str
    audience: dict[str, Any]
    params: dict[str, Any]
    cron_expression: str | None
    start_at: datetime
    end_at: datetime | None
    next_run_at: datetime


@dataclass(slots=True)
class TemplateRow:
    subject_template: str
    body_template: str
    body_format: str


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


async def _fetch_due_tasks(session: AsyncSession, limit: int = 10) -> list[TaskRow]:
    rows = (await session.execute(
        text("""
            SELECT id, name, template_id, channel, audience, params,
                   cron_expression, start_at, end_at, next_run_at
            FROM notifications.t_tasks
            WHERE is_enabled = TRUE
              AND next_run_at <= (now() at time zone 'utc')
            ORDER BY next_run_at
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
        """),
        {"limit": limit},
    )).all()
    return [
        TaskRow(
            id=r.id, name=r.name, template_id=r.template_id, channel=r.channel,
            audience=r.audience, params=r.params, cron_expression=r.cron_expression,
            start_at=r.start_at, end_at=r.end_at, next_run_at=r.next_run_at,
        )
        for r in rows
    ]


async def _fetch_template(session: AsyncSession, template_id: UUID) -> TemplateRow | None:
    row = (await session.execute(
        text("""
            SELECT subject_template, body_template, body_format
            FROM notifications.t_templates
            WHERE id = :tid AND is_active = TRUE
        """),
        {"tid": str(template_id)},
    )).first()
    if row is None:
        return None
    return TemplateRow(
        subject_template=row.subject_template,
        body_template=row.body_template,
        body_format=row.body_format,
    )


async def _expand_audience(
    audience: dict[str, Any], auth: AuthClient,
) -> list[UUID]:
    kind = audience.get("type")
    if kind == "user_ids":
        return [UUID(v) for v in audience.get("values", [])]
    if kind == "all_users":
        return await auth.get_all_user_ids()
    raise ValueError(f"unsupported audience type: {kind!r}")


def _user_context(user: UserData) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "login": user.login,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


async def _bulk_insert_messages(
    session: AsyncSession,
    task: TaskRow,
    template: TemplateRow,
    users: list[UserData],
    run_at: datetime,
) -> int:
    """Вернёт фактически вставленных строк (после ON CONFLICT).

    Per-user контекст из audience.params_by_user (его кладёт alerting-engine,
    ФТ-2) мерджится поверх task.params при рендере шаблона. Для обычных задач
    ключа нет — поведение не меняется.
    """
    if not users:
        return 0

    params_by_user = task.audience.get("params_by_user") or {}
    rendered_rows = []
    for user in users:
        user_params = params_by_user.get(str(user.id))
        params = {**task.params, **user_params} if user_params else task.params
        ctx = {"user": _user_context(user), "params": params}
        try:
            msg = render(
                template.subject_template, template.body_template,
                template.body_format, ctx,
            )
        except Exception:
            logger.exception(
                "render failed task_id=%s user_id=%s — skip", task.id, user.id,
            )
            continue

        recipient = user.email if task.channel == "email" else None
        if task.channel == "email" and not recipient:
            logger.warning(
                "skip task_id=%s user_id=%s — no email for email-channel task",
                task.id, user.id,
            )
            continue

        rendered_rows.append({
            "task_id": str(task.id),
            "run_at": run_at,
            "user_id": str(user.id),
            "channel": task.channel,
            "recipient_address": recipient,
            "subject": msg.subject,
            "body": msg.body,
            "body_format": template.body_format,
        })

    if not rendered_rows:
        return 0

    result = await session.execute(
        text("""
            INSERT INTO notifications.t_messages
                (task_id, run_at, user_id, channel, recipient_address,
                 subject, body, body_format, status)
            VALUES
                (:task_id, :run_at, :user_id, :channel, :recipient_address,
                 :subject, :body, :body_format, 'pending')
            ON CONFLICT ON CONSTRAINT uq_t_messages_task_user_run
            DO NOTHING
        """),
        rendered_rows,
    )
    return result.rowcount or 0


def _compute_next_run_at(task: TaskRow, this_run: datetime) -> datetime | None:
    """Возвращает следующее время запуска или None, если задание одноразовое/истекло."""
    if task.cron_expression is None:
        return None
    base = max(this_run, _utc_now())
    itr = croniter(task.cron_expression, base)
    nxt: datetime = itr.get_next(datetime)
    if task.end_at and nxt > task.end_at:
        return None
    return nxt.replace(tzinfo=None, microsecond=0)


async def _finalize_task(
    session: AsyncSession, task: TaskRow,
    this_run: datetime, next_run: datetime | None,
) -> None:
    if next_run is None:
        # Одноразовое или истёкшее — выключаем
        await session.execute(
            text("""
                UPDATE notifications.t_tasks
                SET is_enabled = FALSE,
                    last_run_at = :this_run,
                    updated_at = (now() at time zone 'utc')
                WHERE id = :id
            """),
            {"id": str(task.id), "this_run": this_run},
        )
    else:
        await session.execute(
            text("""
                UPDATE notifications.t_tasks
                SET last_run_at = :this_run,
                    next_run_at = :next_run,
                    updated_at = (now() at time zone 'utc')
                WHERE id = :id
            """),
            {"id": str(task.id), "this_run": this_run, "next_run": next_run},
        )


async def _process_one_task(session: AsyncSession, task: TaskRow) -> None:
    now = _utc_now()

    # Истёк end_at — выключаем и выходим
    if task.end_at and task.end_at <= now:
        logger.info("task %s end_at expired -> disabling", task.id)
        await _finalize_task(session, task, this_run=now, next_run=None)
        return

    template = await _fetch_template(session, task.template_id)
    if template is None:
        logger.warning("template %s for task %s is inactive/missing — skip run",
                       task.template_id, task.id)
        # Не валим задание — может быть временная деактивация шаблона.
        # Сдвигаем next_run_at на 1 минуту, чтобы не спинить.
        await session.execute(
            text("""
                UPDATE notifications.t_tasks
                SET next_run_at = (now() at time zone 'utc') + interval '1 minute',
                    updated_at = (now() at time zone 'utc')
                WHERE id = :id
            """),
            {"id": str(task.id)},
        )
        return

    auth = AuthClient(session)
    user_ids = await _expand_audience(task.audience, auth)
    users = list((await auth.get_users(user_ids)).values()) if user_ids else []

    if user_ids and len(users) < len(user_ids):
        missing = set(user_ids) - {u.id for u in users}
        logger.warning("task %s: %d user(s) not found in auth: %s",
                       task.id, len(missing), list(missing)[:5])

    run_at = task.next_run_at
    inserted = await _bulk_insert_messages(session, task, template, users, run_at)
    logger.info("task %s run_at=%s expanded=%d inserted=%d",
                task.id, run_at, len(users), inserted)

    next_run = _compute_next_run_at(task, this_run=now)
    await _finalize_task(session, task, this_run=run_at, next_run=next_run)


async def _iteration() -> None:
    async with async_session_maker() as session, session.begin():
        tasks = await _fetch_due_tasks(session, limit=10)
        if not tasks:
            return
        logger.debug("scheduler picked %d due task(s)", len(tasks))
        for task in tasks:
            await _process_one_task(session, task)


async def main() -> None:
    setup_logging("scheduler")
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)
    await run_periodic(
        name="scheduler",
        interval_sec=settings.scheduler_interval,
        iteration=_iteration,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    asyncio.run(main())

"""End-to-end исполнение правила: SQL в StarRocks → задача в notifications.

Минимальная реализация недели 2. Сознательные упрощения (доделать на неделе 3):
  - frequency_cap из t_rules.frequency_cap не применяется (нет проверки
    t_dispatch_history) — лимит уведомлений ляжет на неделю 3.
  - Per-user context (колонка context из SQL правила) игнорируется.
    Передаётся только аудитория user_ids; письмо собирается по дефолтам
    Jinja-шаблона. Per-user params потребует доработки notifications-service.
  - Лог запусков не пишется в t_dispatch_history построчно (нет лимита,
    нет аудита по жалобам — это всё неделя 3). В t_runs пишется агрегат.

Что уже есть и работает:
  - Реальное соединение со StarRocks под alert_reader, выполнение SQL
    правила с тайм-аутом из ALERTING_STARROCKS_QUERY_TIMEOUT_SEC.
  - Парсинг user_id из произвольного резалт-сета (обязательная колонка).
  - Идемпотентный вызов notifications.adm_create_task с ключом
    alerting:{rule_id}:{run_id} — повторный запуск того же run-а
    вернёт тот же task без дубля письма.
  - Атомарная запись t_runs (running → success/failed) + apdate
    t_rules.last_run_at.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import aiomysql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.postgres import async_session_maker
from src.db.starrocks import starrocks_connection


logger = logging.getLogger(__name__)


class RuleNotFoundError(Exception):
    pass


async def execute_rule(rule_id: uuid.UUID, run_id: uuid.UUID | None = None, *, dry_run: bool = False) -> uuid.UUID:
    """Полный цикл срабатывания одного правила.

    Параметры:
        rule_id: UUID правила.
        run_id:  если задан — обновляем существующую t_runs (была создана
                 через adm_trigger_rule / adm_dry_run_rule); если None —
                 создаём новую.
        dry_run: True → SQL выполняется, аудитория считается, но
                 notifications.adm_create_task НЕ вызывается. Анналитик
                 узнаёт matched_users по v_runs.

    Возвращает: run_id.
    """
    async with async_session_maker() as session:
        rule = await _load_rule(session, rule_id)
        if rule is None:
            raise RuleNotFoundError(f"rule_not_found: {rule_id}")

        if run_id is None:
            run_id = await _create_run(session, rule_id, status="running")
        else:
            await _update_run(session, run_id, status="running", started_at=datetime.now(UTC).replace(tzinfo=None))
        await session.commit()

    started_ns = time.monotonic()
    error_msg: str | None = None
    user_ids: list[str] = []
    task_id: uuid.UUID | None = None

    try:
        user_ids = await _fetch_user_ids(rule["sql_query"])

        if user_ids and not dry_run:
            # Усечение по max_users — простая защита от «миллиона юзеров».
            if len(user_ids) > rule["max_users"]:
                logger.warning(
                    "audience exceeds max_users — truncating",
                    extra={
                        "rule_id": str(rule_id),
                        "matched": len(user_ids),
                        "max_users": rule["max_users"],
                    },
                )
                user_ids = user_ids[: rule["max_users"]]

            task_id = await _create_notification_task(
                rule_code=rule["code"],
                template_code=rule["template_code"],
                channel=rule["channel"],
                user_ids=user_ids,
                rule_id=rule_id,
                run_id=run_id,
            )
    except Exception as exc:  # noqa: BLE001 — финализация в любом случае
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.exception("rule execution failed", extra={"rule_id": str(rule_id), "run_id": str(run_id)})

    duration_ms = int((time.monotonic() - started_ns) * 1000)
    matched = len(user_ids)
    dispatched = matched if (task_id is not None and not dry_run) else 0

    async with async_session_maker() as session:
        await _update_run(
            session,
            run_id,
            status="failed" if error_msg else "success",
            finished_at=datetime.now(UTC).replace(tzinfo=None),
            duration_ms=duration_ms,
            matched_users=matched,
            after_cap_users=matched,  # без frequency_cap — равно matched (нед. 3)
            dispatched_users=dispatched,
            notification_task_id=task_id,
            error=error_msg,
        )
        if not error_msg:
            await session.execute(
                text("UPDATE alerting.t_rules SET last_run_at = :ts WHERE id = :rid"),
                {"ts": datetime.now(UTC).replace(tzinfo=None), "rid": rule_id},
            )
        await session.commit()

    logger.info(
        "rule execution finished",
        extra={
            "rule_id": str(rule_id),
            "run_id": str(run_id),
            "status": "failed" if error_msg else "success",
            "matched": matched,
            "dispatched": dispatched,
            "duration_ms": duration_ms,
            "dry_run": dry_run,
        },
    )
    return run_id


# ---------------------------------------------------------------------------
# Внутренние помощники
# ---------------------------------------------------------------------------

async def _load_rule(session: AsyncSession, rule_id: uuid.UUID) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            "SELECT code, sql_query, template_code, channel, max_users "
            "FROM alerting.t_rules WHERE id = :rid AND is_deleted = FALSE"
        ),
        {"rid": rule_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _create_run(session: AsyncSession, rule_id: uuid.UUID, *, status: str) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO alerting.t_runs(rule_id, status) "
            "VALUES (:rid, :st) RETURNING id"
        ),
        {"rid": rule_id, "st": status},
    )
    return result.scalar_one()


async def _update_run(session: AsyncSession, run_id: uuid.UUID, **fields: Any) -> None:
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    params = {"rid": run_id, **fields}
    await session.execute(
        text(f"UPDATE alerting.t_runs SET {assignments} WHERE id = :rid"),
        params,
    )


async def _fetch_user_ids(sql_query: str) -> list[str]:
    """Открыть соединение со StarRocks, выполнить SQL с тайм-аутом, вернуть user_id из первой колонки по имени."""

    async def _runner() -> list[str]:
        async with starrocks_connection() as conn:
            cursor = await conn.cursor(aiomysql.DictCursor)
            try:
                await cursor.execute(sql_query)
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return _extract_user_ids(rows)

    return await asyncio.wait_for(_runner(), timeout=settings.starrocks_query_timeout_sec)


def _extract_user_ids(rows: Iterable[dict[str, Any]]) -> list[str]:
    user_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if "user_id" not in row:
            raise ValueError(
                f"rule SQL must return column 'user_id'; got columns: {list(row)}"
            )
        uid = row["user_id"]
        if uid is None:
            continue
        uid_str = str(uid)
        if uid_str in seen:
            continue
        seen.add(uid_str)
        user_ids.append(uid_str)
    return user_ids


async def _create_notification_task(
    *,
    rule_code: str,
    template_code: str,
    channel: str,
    user_ids: list[str],
    rule_id: uuid.UUID,
    run_id: uuid.UUID,
) -> uuid.UUID:
    """Вызвать notifications.adm_create_task с идемпотентным ключом.

    Идемпотентность: 'alerting:{rule_id}:{run_id}'. Повторный запуск того же
    run-а вернёт тот же task_id без второго письма (правда, для запасных
    окон при сбое — это пока обеспечивается только при том же run_id; при
    новом run_id будет новый task. Полное восстановление — неделя 3).
    """
    audience = {"type": "user_ids", "values": user_ids}
    params = {"rule_code": rule_code}
    ikey = f"alerting:{rule_id}:{run_id}"

    async with async_session_maker() as session:
        result = await session.execute(
            text(
                "SELECT notifications.adm_create_task("
                "  p_template_code   := :tc,"
                "  p_channel         := :ch,"
                "  p_audience        := CAST(:aud AS JSONB),"
                "  p_name            := :name,"
                "  p_params          := CAST(:params AS JSONB),"
                "  p_idempotency_key := :ikey,"
                "  p_created_by      := 'alerting-engine'"
                ")"
            ),
            {
                "tc": template_code,
                "ch": channel,
                "aud": json.dumps(audience),
                "name": f"alerting:{rule_code}",
                "params": json.dumps(params),
                "ikey": ikey,
            },
        )
        task_id = result.scalar_one()
        await session.commit()
        return task_id

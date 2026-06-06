"""End-to-end исполнение правила: SQL в StarRocks → задача в notifications.

Полный цикл (неделя 3):
  1. Пометить запуск running (отдельный коммит — чтобы его видел recovery).
  2. Выполнить SQL правила в StarRocks под alert_reader, с тайм-аутом; получить
     аудиторию (user_id + опциональный per-user context из колонки `context`).
  3. Одной атомарной транзакцией Postgres:
       - применить двухуровневый frequency cap по t_dispatch_history (ФТ-3);
       - записать t_dispatch_history по оставшимся пользователям (ФТ-8);
       - создать задачу notifications.adm_create_task с per-user context (ФТ-2)
         и идемпотентным ключом alerting:{rule_id}:{run_id};
       - финализировать t_runs (success + счётчики) и t_rules.last_run_at.

Атомарность фазы 3 — фундамент идемпотентности и recovery (НФТ-3): статус
'running' ⟺ ничего не закоммичено ⟺ запуск можно безопасно повторить с тем же
run_id. Идемпотентный ключ — вторая страховка от дублей.

dry_run: cap считается (для after_cap_users), но t_dispatch_history и задача
НЕ пишутся.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import aiomysql
from sqlalchemy import text

from src.core.config import settings
from src.db.postgres import async_session_maker
from src.db.starrocks import starrocks_connection


if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

# Аудитория правила: пары (user_id, context) — context опционален (ФТ-2).
Audience = list[tuple[str, dict[str, Any] | None]]


class RuleNotFoundError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def execute_rule(rule_id: uuid.UUID, run_id: uuid.UUID | None = None, *, dry_run: bool = False) -> uuid.UUID:
    """Полный цикл срабатывания одного правила.

    rule_id: UUID правила.
    run_id:  если задан — обновляем существующую t_runs (создана через
             adm_trigger_rule/adm_dry_run_rule или это recovery); если None —
             создаём новую (плановый тик).
    dry_run: True → SQL выполняется и cap считается, но задача НЕ создаётся.

    Возвращает run_id.
    """
    # --- Фаза 1: пометить запуск running (отдельный коммит) ----------------
    async with async_session_maker() as session:
        rule = await _load_rule(session, rule_id)
        if rule is None:
            raise RuleNotFoundError(f"rule_not_found: {rule_id}")
        if run_id is None:
            run_id = await _create_run(session, rule_id)
        else:
            await _update_run(session, run_id, status="running", started_at=_utc_now())
        await session.commit()

    started_ns = time.monotonic()

    # --- Фаза 2: выборка из StarRocks (вне Postgres-транзакции) -------------
    try:
        audience = await _fetch_audience(rule["sql_query"])
    except Exception as exc:
        await _finalize_failed(run_id, exc, started_ns)
        logger.exception("rule SQL failed", extra={"rule_id": str(rule_id), "run_id": str(run_id)})
        return run_id

    matched = len(audience)

    # --- Фаза 3: атомарная транзакция (cap → history → task → финализация) --
    try:
        async with async_session_maker() as session, session.begin():
            blocked = await _blocked_by_cap(session, rule_id, rule["frequency_cap"], audience)
            kept = _filter_by_cap(audience, blocked)
            if len(kept) > rule["max_users"]:
                logger.warning(
                    "audience exceeds max_users — truncating",
                    extra={"rule_id": str(rule_id), "after_cap": len(kept), "max_users": rule["max_users"]},
                )
                kept = kept[: rule["max_users"]]

            task_id: uuid.UUID | None = None
            if kept and not dry_run:
                await _insert_dispatch_history(session, rule_id, rule["channel"], kept)
                task_id = await _create_notification_task(session, rule, kept, rule_id, run_id)

            dispatched = len(kept) if task_id is not None else 0
            duration_ms = int((time.monotonic() - started_ns) * 1000)
            await _update_run(
                session, run_id,
                status="success",
                finished_at=_utc_now(),
                duration_ms=duration_ms,
                matched_users=matched,
                after_cap_users=len(kept),
                dispatched_users=dispatched,
                notification_task_id=task_id,
            )
            await session.execute(
                text("UPDATE alerting.t_rules SET last_run_at = :ts WHERE id = :rid"),
                {"ts": _utc_now(), "rid": rule_id},
            )
    except Exception as exc:
        # Транзакция откатилась — фиксируем failed отдельной транзакцией.
        await _finalize_failed(run_id, exc, started_ns)
        logger.exception("rule dispatch failed", extra={"rule_id": str(rule_id), "run_id": str(run_id)})
        return run_id

    logger.info(
        "rule execution finished",
        extra={
            "rule_id": str(rule_id), "run_id": str(run_id), "status": "success",
            "matched": matched, "after_cap": len(kept), "dispatched": dispatched,
            "duration_ms": duration_ms, "dry_run": dry_run,
        },
    )
    return run_id


# ---------------------------------------------------------------------------
# Frequency cap — чистая логика отделена от запросов ради юнит-тестов
# ---------------------------------------------------------------------------

def _filter_by_cap(audience: Audience, blocked: set[str]) -> Audience:
    """Оставить пользователей, не попавших под лимит уведомлений."""
    return [(uid, ctx) for uid, ctx in audience if uid not in blocked]


def _coerce_cap(cap: object) -> dict[str, Any]:
    """frequency_cap из t_rules → dict (asyncpg может вернуть JSONB строкой)."""
    if isinstance(cap, str):
        return json.loads(cap) if cap.strip() else {}
    return cap or {} if isinstance(cap, dict) else {}


async def _blocked_by_cap(session: AsyncSession, rule_id: uuid.UUID, cap_raw: object, audience: Audience) -> set[str]:
    """Множество user_id, которым слать нельзя из-за двухуровневого лимита (ФТ-3).

      per_rule_per_user_days — не чаще раза в N дней по ЭТОМУ правилу;
      per_user_per_day       — общий потолок M писем на пользователя в сутки.
    Любого ключа может не быть → соответствующий уровень не ограничивает.
    """
    cap = _coerce_cap(cap_raw)
    if not audience or not cap:
        return set()

    user_ids = [uid for uid, _ in audience]
    blocked: set[str] = set()

    per_rule_days = cap.get("per_rule_per_user_days")
    if per_rule_days:
        rows = await session.execute(
            text(
                "SELECT DISTINCT user_id::text AS uid FROM alerting.t_dispatch_history "
                "WHERE rule_id = :rid AND user_id::text = ANY(:uids) "
                "  AND sent_at > (now() AT TIME ZONE 'utc') - make_interval(days => :days)",
            ),
            {"rid": rule_id, "uids": user_ids, "days": int(per_rule_days)},
        )
        blocked.update(r.uid for r in rows)

    per_day = cap.get("per_user_per_day")
    if per_day:
        rows = await session.execute(
            text(
                "SELECT user_id::text AS uid FROM alerting.t_dispatch_history "
                "WHERE user_id::text = ANY(:uids) "
                "  AND sent_at >= date_trunc('day', (now() AT TIME ZONE 'utc')) "
                "GROUP BY user_id HAVING count(*) >= :cap",
            ),
            {"uids": user_ids, "cap": int(per_day)},
        )
        blocked.update(r.uid for r in rows)

    return blocked


# ---------------------------------------------------------------------------
# StarRocks — выборка и разбор контракта колонок (тоже под юнит-тесты)
# ---------------------------------------------------------------------------

async def _fetch_audience(sql_query: str) -> Audience:
    """Выполнить SQL в StarRocks с тайм-аутом, вернуть (user_id, context)."""

    async def _runner() -> Audience:
        async with starrocks_connection() as conn:
            cursor = await conn.cursor(aiomysql.DictCursor)
            try:
                await cursor.execute(sql_query)
                rows = await cursor.fetchall()
            finally:
                await cursor.close()
        return _extract_audience(rows)

    return await asyncio.wait_for(_runner(), timeout=settings.starrocks_query_timeout_sec)


def _extract_audience(rows: Iterable[dict[str, Any]]) -> Audience:
    """Разобрать резалт-сет: обязательна колонка user_id, опциональна context."""
    audience: Audience = []
    seen: set[str] = set()
    for row in rows:
        if "user_id" not in row:
            raise ValueError(f"rule SQL must return column 'user_id'; got columns: {list(row)}")
        uid = row["user_id"]
        if uid is None:
            continue
        uid_str = str(uid)
        if uid_str in seen:
            continue
        seen.add(uid_str)
        audience.append((uid_str, _parse_context(row.get("context"))))
    return audience


def _parse_context(value: object) -> dict[str, Any] | None:
    """context из StarRocks JSON → dict (или None, если пусто/не объект)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------------
# Postgres — запись (всё в рамках переданной транзакции, кроме фаз 1 и failed)
# ---------------------------------------------------------------------------

async def _load_rule(session: AsyncSession, rule_id: uuid.UUID) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            "SELECT code, sql_query, template_code, channel, max_users, frequency_cap "
            "FROM alerting.t_rules WHERE id = :rid AND is_deleted = FALSE",
        ),
        {"rid": rule_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _create_run(session: AsyncSession, rule_id: uuid.UUID) -> uuid.UUID:
    result = await session.execute(
        text("INSERT INTO alerting.t_runs(rule_id, status) VALUES (:rid, 'running') RETURNING id"),
        {"rid": rule_id},
    )
    return result.scalar_one()


async def _update_run(session: AsyncSession, run_id: uuid.UUID, **fields) -> None:
    assignments = ", ".join(f"{k} = :{k}" for k in fields)  # ключи внутренние, не пользовательский ввод
    await session.execute(
        text(f"UPDATE alerting.t_runs SET {assignments} WHERE id = :rid"),  # noqa: S608
        {"rid": run_id, **fields},
    )


async def _finalize_failed(run_id: uuid.UUID, exc: Exception, started_ns: float) -> None:
    """Зафиксировать прерванный запуск как failed (отдельной транзакцией)."""
    async with async_session_maker() as session:
        await _update_run(
            session, run_id,
            status="failed",
            finished_at=_utc_now(),
            duration_ms=int((time.monotonic() - started_ns) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )
        await session.commit()


async def _insert_dispatch_history(session: AsyncSession, rule_id: uuid.UUID, channel: str, kept: Audience) -> None:
    """Записать строки истории отправок (попадают в недельную партицию по now())."""
    await session.execute(
        text(
            "INSERT INTO alerting.t_dispatch_history(rule_id, user_id, channel, sent_at) "
            "VALUES (:rid, CAST(:uid AS uuid), :ch, (now() AT TIME ZONE 'utc'))",
        ),
        [{"rid": rule_id, "uid": uid, "ch": channel} for uid, _ in kept],
    )


async def _create_notification_task(
    session: AsyncSession,
    rule: dict[str, Any],
    kept: Audience,
    rule_id: uuid.UUID,
    run_id: uuid.UUID,
) -> uuid.UUID:
    """Вызвать notifications.adm_create_task в рамках текущей транзакции.

    Per-user context (ФТ-2) передаётся в audience.params_by_user — scheduler
    notifications мерджит его поверх task-level params при рендере шаблона.
    Идемпотентность: ключ alerting:{rule_id}:{run_id} (повтор того же run-а
    вернёт тот же task без второго письма).
    """
    user_ids = [uid for uid, _ in kept]
    params_by_user = {uid: ctx for uid, ctx in kept if ctx}
    audience: dict[str, Any] = {"type": "user_ids", "values": user_ids}
    if params_by_user:
        audience["params_by_user"] = params_by_user

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
            ")",
        ),
        {
            "tc": rule["template_code"],
            "ch": rule["channel"],
            "aud": json.dumps(audience),
            "name": f"alerting:{rule['code']}",
            "params": json.dumps({"rule_code": rule["code"]}),
            "ikey": f"alerting:{rule_id}:{run_id}",
        },
    )
    return result.scalar_one()

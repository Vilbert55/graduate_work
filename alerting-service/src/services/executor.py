"""Исполнение одного срабатывания правила: SQL в StarRocks -> задача в notifications.

Работа делится на три фазы:
  1. Пометить запуск как running и сразу закоммитить. Отдельный коммит нужен,
     чтобы при сбое движка этот запуск увидел recovery и дозавершил его.
  2. Выполнить SQL правила в StarRocks (под alert_reader, с тайм-аутом) и
     получить аудиторию: user_id + опциональный per-user context из колонки
     context. Выполняется вне транзакции Postgres, чтобы внешний запрос не
     держал блокировку в БД.
  3. Одной транзакцией Postgres: применить frequency cap, записать историю
     отправок, создать задачу в notifications с per-user context и финализировать
     журнал запуска. Срабатывает по принципу "либо всё, либо ничего".

Почему фаза 3 атомарна: пока запуск в статусе running, в БД по нему ещё ничего не
закоммичено, поэтому его можно безопасно повторить с тем же run_id — дублей писем
не будет. Идемпотентный ключ alerting:{rule_id}:{run_id} в adm_create_task — это
вторая страховка от повторной отправки.

dry_run: cap считается (чтобы показать размер аудитории до и после лимита), но
история и задача НЕ пишутся — писем нет.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
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

# Аудитория правила: пары (user_id, context); context опционален.
Audience = list[tuple[str, dict[str, Any] | None]]


class RuleNotFoundError(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def execute_rule(rule_id: uuid.UUID, run_id: uuid.UUID | None = None, *, dry_run: bool = False) -> uuid.UUID:
    """Выполнить полный цикл одного срабатывания правила.

    rule_id: UUID правила.
    run_id:  если задан — обновляем существующую запись t_runs (её создала
             adm_trigger_rule / adm_dry_run_rule, либо это recovery); если None —
             создаём новую (плановый запуск по cron).
    dry_run: True — SQL выполняется и cap считается, но задача НЕ создаётся.

    Возвращает run_id.
    """
    # Фаза 1: пометить запуск running и закоммитить (его увидит recovery при сбое).
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

    # Фаза 2: выборка из StarRocks (вне транзакции Postgres).
    try:
        audience = await _fetch_audience(rule["sql_query"])
    except Exception as exc:
        await _finalize_failed(run_id, exc, started_ns)
        logger.exception("rule SQL failed", extra={"rule_id": str(rule_id), "run_id": str(run_id)})
        return run_id

    matched = len(audience)

    # Фаза 3: одна транзакция — cap, история, задача, финализация.
    try:
        async with async_session_maker() as session, session.begin():
            cap = FrequencyCap.build(rule["frequency_cap"], settings.global_per_user_per_day)
            blocked = await _blocked_by_cap(session, rule_id, cap, audience)
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


# Frequency cap. Чистые функции (разбор настроек и фильтр) отделены от запросов
# к БД — это позволяет покрыть логику юнит-тестами без подключения к Postgres.

@dataclass(frozen=True, slots=True)
class FrequencyCap:
    """Лимиты, применяемые к аудитории одного срабатывания.

    per_rule_per_user_days — берётся из самого правила: не слать одному
        пользователю чаще раза в N дней по ЭТОМУ правилу. None — уровень выключен.
    per_user_per_day — общий потолок писем на пользователя в сутки по ВСЕМ
        правилам. Это системная настройка движка (одна на все правила), а не
        свойство правила. None — потолок выключен.
    """

    per_rule_per_user_days: int | None = None
    per_user_per_day: int | None = None

    @classmethod
    def build(cls, rule_cap: dict[str, Any] | str | None, global_per_user_per_day: int) -> FrequencyCap:
        """Возвращает эффективный cap из frequency_cap правила и глобальной настройки.

        rule_cap: значение t_rules.frequency_cap (asyncpg может вернуть JSONB и как
            dict, и строкой). Берём из него только per_rule_per_user_days.
        global_per_user_per_day: настройка движка ALERTING_GLOBAL_PER_USER_PER_DAY,
            общий дневной потолок на пользователя (0 — выключен).
        """
        cap: Any = rule_cap
        if isinstance(cap, str):
            cap = json.loads(cap) if cap.strip() else {}
        if not isinstance(cap, dict):
            cap = {}
        return cls(
            per_rule_per_user_days=_pos_int_or_none(cap.get("per_rule_per_user_days")),
            per_user_per_day=_pos_int_or_none(global_per_user_per_day),
        )

    @property
    def is_empty(self) -> bool:
        """True, если ни один уровень лимита не задан."""
        return self.per_rule_per_user_days is None and self.per_user_per_day is None


def _pos_int_or_none(value: int | str | None) -> int | None:
    """Возвращает положительный int или None (0, None и нечисловое -> None)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _filter_by_cap(audience: Audience, blocked: set[str]) -> Audience:
    """Возвращает аудиторию без пользователей, попавших под лимит уведомлений.

    audience: исходные пары (user_id, context).
    blocked: user_id, которым слать нельзя (результат _blocked_by_cap).
    """
    return [(uid, ctx) for uid, ctx in audience if uid not in blocked]


async def _blocked_by_cap(session: AsyncSession, rule_id: uuid.UUID, cap: FrequencyCap, audience: Audience) -> set[str]:
    """Возвращает множество user_id, которым нельзя слать из-за лимитов уведомлений.

    session: открытая транзакция Postgres (читаем t_dispatch_history в ней же).
    rule_id: правило, по которому считаем интервал per_rule_per_user_days.
    cap: эффективные лимиты (см. FrequencyCap).
    audience: кандидаты на рассылку; проверяем только их user_id.

    Уровни независимы — пользователь блокируется, если сработал любой из них:
      per_rule_per_user_days — уже получал ЭТО правило за последние N дней;
      per_user_per_day — уже получил >= M писем сегодня по всем правилам.
    """
    if not audience or cap.is_empty:
        return set()

    user_ids = [uid for uid, _ in audience]
    blocked: set[str] = set()

    if cap.per_rule_per_user_days:
        rows = await session.execute(
            text(
                "SELECT DISTINCT user_id::text AS uid FROM alerting.t_dispatch_history "
                "WHERE rule_id = :rid AND user_id::text = ANY(:uids) "
                "  AND sent_at > (now() AT TIME ZONE 'utc') - make_interval(days => :days)",
            ),
            {"rid": rule_id, "uids": user_ids, "days": cap.per_rule_per_user_days},
        )
        blocked.update(r.uid for r in rows)

    if cap.per_user_per_day:
        rows = await session.execute(
            text(
                "SELECT user_id::text AS uid FROM alerting.t_dispatch_history "
                "WHERE user_id::text = ANY(:uids) "
                "  AND sent_at >= date_trunc('day', (now() AT TIME ZONE 'utc')) "
                "GROUP BY user_id HAVING count(*) >= :cap",
            ),
            {"uids": user_ids, "cap": cap.per_user_per_day},
        )
        blocked.update(r.uid for r in rows)

    return blocked


# StarRocks: выборка и разбор контракта колонок результата.

async def _fetch_audience(sql_query: str) -> Audience:
    """Возвращает аудиторию: выполнить SQL правила в StarRocks с тайм-аутом."""

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
    """Возвращает аудиторию из резалт-сета. Колонка user_id обязательна, context — нет.

    rows: строки результата SQL правила. Дубли user_id схлопываются (берём
    первый context), строки с NULL user_id пропускаются.
    """
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


def _parse_context(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """Возвращает context как dict (или None, если пусто/не объект).

    value: значение колонки context из StarRocks. JSON приходит строкой, поэтому
    её разбираем; всё, что не объект, считаем отсутствующим context.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


# Postgres: запись результата. Всё в рамках переданной транзакции, кроме фазы 1
# (отдельный коммит running) и фиксации failed.

async def _load_rule(session: AsyncSession, rule_id: uuid.UUID) -> dict[str, Any] | None:
    """Возвращает поля правила, нужные для исполнения, или None, если правила нет."""
    result = await session.execute(
        text(
            "SELECT code, sql_query, template_code, channel, max_users, frequency_cap "
            "FROM alerting.t_rules WHERE id = :rid",
        ),
        {"rid": rule_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _create_run(session: AsyncSession, rule_id: uuid.UUID) -> uuid.UUID:
    """Создать запись запуска со статусом running. Возвращает её run_id."""
    result = await session.execute(
        text("INSERT INTO alerting.t_runs(rule_id, status) VALUES (:rid, 'running') RETURNING id"),
        {"rid": rule_id},
    )
    return result.scalar_one()


async def _update_run(session: AsyncSession, run_id: uuid.UUID, **fields) -> None:
    """Обновить переданные поля запуска t_runs (ключи — внутренние, не ввод пользователя)."""
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
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
    """Записать строки в историю отправок.

    sent_at = now(), поэтому строки попадают в текущую недельную партицию
    t_dispatch_history. Эта история — основа frequency cap и журнал для аудита.
    """
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
    """Создать задачу notifications.adm_create_task в текущей транзакции. Возвращает её id.

    Per-user context кладём в audience.params_by_user — scheduler notifications
    мерджит его поверх общих params при рендере шаблона, поэтому у каждого письма
    свои подстановки. Идемпотентность: ключ alerting:{rule_id}:{run_id} — повтор
    того же запуска вернёт ту же задачу, второго письма не будет.

    rule_code и run_id уходят в params: шаблон строит из них ссылку
    /ugc/email/click. run_id делает ссылку уникальной для каждого срабатывания
    правила (новый запуск -> новая ссылка -> отдельный переход), а recovery с тем
    же run_id даёт ту же ссылку (без задвоения).
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
            "params": json.dumps({"rule_code": rule["code"], "run_id": str(run_id)}),
            "ikey": f"alerting:{rule_id}:{run_id}",
        },
    )
    return result.scalar_one()

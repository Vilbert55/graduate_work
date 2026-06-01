"""trigger-events — генератор событий в Kafka от демо-юзеров.

Сценарии:
  winback        — серия view-событий 30..8 дней назад + тишина последние 7 дней.
                   Запускает в mv_user_activity пользователей с
                   was_active_last_month=TRUE и last_watch_at < now()-7d.
  segment_trend  — всплеск просмотров одного фильма от пользователей одного
                   сегмента за последние 24ч. Триггерит mv_segment_film_activity.
  weekend_burst  — view-события только в субботу-воскресенье прошлой недели.
                   Триггерит mv_weekend_film_activity (join с dim_date.is_weekend).

Замечание про дедупликацию: StarRocks user_events — Primary Key table,
повторная отправка одного и того же request_id не создаёт дубля. Поэтому
сценарии безопасно перезапускать.
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import typer
from kafka import KafkaProducer

from src.config import settings
from src.segments import AGE_BANDS, band_range


SCENARIOS = ("winback", "segment_trend", "weekend_burst")


def _make_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        retries=3,
        compression_type="gzip",
    )


async def _fetch_demo_users(conn: asyncpg.Connection, segment: str | None, limit: int) -> list[asyncpg.Record]:
    base_sql = "SELECT id::text AS user_id, gender, age, country FROM auth.users WHERE is_demo"
    if segment:
        try:
            g, a, c = segment.split("_")
        except ValueError as exc:
            raise typer.BadParameter("--segment expected 'gender_age_country'") from exc
        if a not in AGE_BANDS:
            raise typer.BadParameter(f"--segment age band must be one of: {', '.join(AGE_BANDS)}")
        lo, hi = band_range(a)
        return await conn.fetch(
            base_sql + " AND gender=$1 AND age BETWEEN $2 AND $3 AND country=$4 LIMIT $5",
            g, lo, hi, c, limit,
        )
    return await conn.fetch(base_sql + " ORDER BY random() LIMIT $1", limit)


async def _fetch_films(conn: asyncpg.Connection, limit: int) -> list[str]:
    rows = await conn.fetch(
        "SELECT id::text FROM content.film_work ORDER BY random() LIMIT $1",
        limit,
    )
    return [r["id"] for r in rows]


def _emit_view(producer: KafkaProducer, user_id: str, film_id: str, client_time: datetime) -> None:
    event = {
        "request_id": str(uuid.uuid4()),
        "user_id": user_id,
        "film_id": film_id,
        "progress_seconds": random.randint(60, 7200),
        "timestamp": client_time.isoformat(),
        "server_timestamp": datetime.now(UTC).isoformat(),
    }
    producer.send(settings.kafka_topic_views, value=event, key=user_id)


def _last_weekend_window() -> tuple[datetime, datetime]:
    """Возвращает (start, end) последней пары суббота-воскресенье в UTC."""
    today = datetime.now(UTC).date()
    # Понедельник = 0 ... воскресенье = 6
    days_since_sun = (today.weekday() + 1) % 7  # сколько дней назад было прошлое воскресенье
    last_sunday = today - timedelta(days=days_since_sun if days_since_sun > 0 else 7)
    last_saturday = last_sunday - timedelta(days=1)
    start = datetime.combine(last_saturday, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(last_sunday, datetime.max.time(), tzinfo=UTC)
    return start, end


async def _run_winback(count: int, segment: str | None) -> int:
    """Каждому демо-юзеру: 10–15 view-событий 30..8 дней назад, потом тишина."""
    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        users = await _fetch_demo_users(conn, segment, count)
        films = await _fetch_films(conn, 30)
    finally:
        await conn.close()

    if not users or not films:
        typer.echo("no demo users or no films — nothing to do")
        return 0

    producer = _make_producer()
    emitted = 0
    try:
        for u in users:
            n_events = random.randint(10, 15)
            for _ in range(n_events):
                days_ago = random.randint(8, 30)
                hours_ago = random.randint(0, 23)
                ct = datetime.now(UTC) - timedelta(days=days_ago, hours=hours_ago)
                _emit_view(producer, u["user_id"], random.choice(films), ct)
                emitted += 1
    finally:
        producer.flush(timeout=30)
        producer.close()
    return emitted


async def _run_segment_trend(count: int, segment: str | None) -> int:
    """Всплеск просмотров одного фильма от юзеров сегмента за последние 24ч."""
    seg = segment or "female_25-34_RU"
    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        users = await _fetch_demo_users(conn, seg, count)
        films = await _fetch_films(conn, 1)
    finally:
        await conn.close()

    if not users or not films:
        typer.echo(f"no demo users in segment {seg} or no films — nothing to do")
        return 0

    trending_film = films[0]
    producer = _make_producer()
    emitted = 0
    try:
        for u in users:
            ct = datetime.now(UTC) - timedelta(hours=random.randint(0, 23))
            _emit_view(producer, u["user_id"], trending_film, ct)
            emitted += 1
    finally:
        producer.flush(timeout=30)
        producer.close()
    typer.echo(f"trending film_id={trending_film}, segment={seg}")
    return emitted


async def _run_weekend_burst(count: int, segment: str | None) -> int:
    """view-события только субботы/воскресенья прошлой недели."""
    start, end = _last_weekend_window()
    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        users = await _fetch_demo_users(conn, segment, count)
        films = await _fetch_films(conn, 5)
    finally:
        await conn.close()

    if not users or not films:
        typer.echo("no demo users or no films — nothing to do")
        return 0

    span_sec = int((end - start).total_seconds())
    producer = _make_producer()
    emitted = 0
    try:
        for u in users:
            for _ in range(random.randint(3, 6)):
                ct = start + timedelta(seconds=random.randint(0, span_sec))
                _emit_view(producer, u["user_id"], random.choice(films), ct)
                emitted += 1
    finally:
        producer.flush(timeout=30)
        producer.close()
    typer.echo(f"weekend window: {start.isoformat()} .. {end.isoformat()}")
    return emitted


def trigger_events_cmd(
    scenario: str = typer.Option(..., "--scenario", help=f"Сценарий: {' | '.join(SCENARIOS)}"),
    count: int = typer.Option(30, "--count", "-n", help="Сколько юзеров вовлечь"),
    segment: str | None = typer.Option(
        None, "--segment", "-s",
        help="Сегмент 'gender_age_country' (для segment_trend обязателен по смыслу)",
    ),
) -> None:
    """Сгенерировать пакет событий по сценарию для демонстрации правил."""
    if scenario not in SCENARIOS:
        raise typer.BadParameter(f"--scenario must be one of: {', '.join(SCENARIOS)}")

    runners = {
        "winback": _run_winback,
        "segment_trend": _run_segment_trend,
        "weekend_burst": _run_weekend_burst,
    }
    emitted = asyncio.run(runners[scenario](count, segment))
    typer.echo(f"OK: scenario={scenario} emitted {emitted} events")

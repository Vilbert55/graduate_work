"""Подключение к StarRocks по MySQL-протоколу.

На неделе 2 — только заглушка. Полноценный движок (выполнение SQL правила,
проверка тайм-аута, парсинг колонок user_id/context) — задача недели 3.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiomysql

from src.core.config import settings


@asynccontextmanager
async def starrocks_connection() -> AsyncIterator[aiomysql.Connection]:
    """Открыть короткоживущее соединение с StarRocks под ролью alert_reader."""
    conn = await aiomysql.connect(
        host=settings.starrocks_host,
        port=settings.starrocks_port,
        user=settings.starrocks_user,
        password=settings.starrocks_password,
        db=settings.starrocks_db,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()

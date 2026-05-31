"""Подключение к StarRocks по MySQL-протоколу.

Короткоживущее соединение под ролью alert_reader (только SELECT на
ugc_analytics). Выдаётся как async-контекст-менеджер; executor открывает
его на время выполнения SQL правила и закрывает сразу после. Тайм-аут
запроса и парсинг колонки user_id — на стороне services.executor.
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

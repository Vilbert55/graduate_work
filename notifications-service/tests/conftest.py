"""Общие фикстуры для тестов.

Тесты предполагают запущенный docker-compose с полной инфраструктурой:
  - movies-db (PostgreSQL с применёнными миграциями)
  - movies-rabbitmq (с инициализированной топологией)
  - movies-mailpit (SMTP-приёмник + API для проверки писем)
  - все воркеры (scheduler, publisher, email-sender)
"""
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.config import settings


@pytest.fixture
def engine():
    """Создаёт AsyncEngine для текущего теста.

    Намеренно function-scoped: session-scoped AsyncEngine привязывается
    к event loop первого использовавшего его теста и ломается в других тестах
    с 'Future attached to a different loop'.
    """
    return create_async_engine(settings.database_url)


@pytest.fixture
def session_maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def mailpit():
    """HTTP-клиент к Mailpit API; очищает ящик перед тестом."""
    async with httpx.AsyncClient(base_url="http://localhost:8025") as client:
        await client.delete("/api/v1/messages")
        yield client


@pytest.fixture
async def admin_conn():
    """Соединение с правами роли notification_admin (через SET LOCAL ROLE).

    Создаёт собственный AsyncEngine — изолировано от фикстуры engine,
    чтобы избежать конфликтов event loop между тестами.

    SET LOCAL ROLE ограничен текущей транзакцией. Для изоляции каждого
    проверяемого вызова в тестах используйте begin_nested() — SAVEPOINT
    откатывает ошибку PostgreSQL, оставляя внешнюю транзакцию рабочей.
    """
    _engine = create_async_engine(settings.database_url)
    try:
        async with _engine.connect() as conn:
            trans = await conn.begin()
            await conn.execute(text("SET LOCAL ROLE notification_admin"))
            yield conn
            await trans.rollback()
    finally:
        await _engine.dispose()

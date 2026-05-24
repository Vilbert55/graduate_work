import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

from src.core.config import settings
from src.db.postgres import SCHEMA_NAME, Base

# Импортируем модели, чтобы они зарегистрировались в Base.metadata
from src.models import entity  # noqa: F401


# Конфиг Alembic
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные для автогенерации
target_metadata = Base.metadata

# URL БД берём из настроек сервиса
config.set_main_option("sqlalchemy.url", str(settings.database_url))


async def async_create_schema() -> None:
    """Создать схему БД community_content, если её ещё нет."""
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}"'))
        await conn.commit()
    await engine.dispose()


def include_object(object, name, type_, reflected, compare_to):  # noqa: ARG001, A002
    """Фильтр: учитываем только таблицы из своей схемы."""
    if type_ == "table":
        return object.schema == SCHEMA_NAME
    return True


def run_migrations_offline() -> None:
    """Запуск миграций в offline-режиме."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA_NAME,
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Запустить миграции с переданным соединением."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA_NAME,
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Создать асинхронный движок и запустить миграции."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Запуск миграций в online-режиме."""
    asyncio.run(async_create_schema())
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

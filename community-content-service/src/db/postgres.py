from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.core.config import settings


# Название схемы БД, в которой хранятся все таблицы сервиса
SCHEMA_NAME = 'community_content'

# Базовый класс для моделей
Base = declarative_base()

# Асинхронный движок и фабрика сессий
engine = create_async_engine(settings.database_url, echo=settings.debug, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Предоставить асинхронную сессию БД (для FastAPI Depends)."""
    async with async_session() as session:
        yield session

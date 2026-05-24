from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.core.config import settings


# Создаём базовый класс для будущих моделей
Base = declarative_base()
# Создаём движок
# Настройки подключения к БД передаём из переменных окружения, которые заранее загружены в файл настроек
dsn = settings.database_url
engine = create_async_engine(dsn, echo=settings.debug, future=True)
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


# Функция понадобится при внедрении зависимостей
# Dependency
async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session

from uuid import UUID

from fastapi import Request
from redis.asyncio import Redis

from src.core.config import settings


async def create_redis_client() -> Redis:  # noqa: RUF029
    """Создаёт новый клиент Redis (используется только при старте приложения)."""
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )


def get_redis(request: Request) -> Redis:
    """Возвращает существующий клиент Redis из состояния приложения."""
    return request.app.state.redis


def redis_key_user(user_id: UUID) -> str:
    """Формирует ключ redis по которому содержится общая информация о пользователе"""
    return f"user:{user_id}"


def redis_key_user_permissions(user_id: UUID) -> str:
    """Формирует ключ redis по которому содержится информация о разрешениях пользователя"""
    return f"user:{user_id}:permissions"

from abc import ABC, abstractmethod
from typing import Any

from redis.asyncio import Redis


class Cache(ABC):
    """Абстрактный класс для работы с кешем."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Получить значение по ключу."""

    @abstractmethod
    async def set(self, key: str, value: Any, expire: int) -> None:
        """Установить значение с временем жизни (сек)."""


class RedisCache(Cache):
    """Реализация кеша на Redis."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get(self, key: str) -> Any | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: Any, expire: int) -> None:
        await self._redis.set(key, value, expire)

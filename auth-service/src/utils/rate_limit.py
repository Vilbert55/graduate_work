from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from src.core.exceptions import RateLimitExceededError
from src.db.redis import get_redis


def rate_limit(requests: int, period: int):
    """Фабрика зависимостей для ограничения частоты запросов.

    Args:
        requests (int): максимальное количество запросов за период
        period (int): период в секундах

    Returns:
        limiter: функция-зависимость, проверяющая лимит для текущего IP
    """
    async def limiter(
        request: Request,
        redis: Annotated[Redis, Depends(get_redis)],
    ) -> None:
        ip = request.client.host
        key = f"rate_limit:{request.url.path}:{ip}"

        # Атомарное увеличение счётчика
        pipe = redis.pipeline()
        pipe.incr(key)                     # увеличить счётчик, возвращает новое значение
        pipe.expire(key, period, nx=True)  # устанавливаем TTL, только если ключа ещё не было
        results = await pipe.execute()     # [new_value, expire_result]

        current = results[0]               # новое значение счётчика после инкремента
        if current > requests:
            raise RateLimitExceededError

    return limiter

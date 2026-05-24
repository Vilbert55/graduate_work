from redis.asyncio import Redis

from src.core.config import settings


async def get_redis_client() -> Redis:  # noqa: RUF029
    """Создать и вернуть клиент Redis."""
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=0,
        decode_responses=True,  # автоматически декодировать байты в строки
        encoding='utf-8',
    )

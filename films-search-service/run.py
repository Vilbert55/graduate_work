import asyncio
import logging.config

import uvicorn
from elasticsearch import AsyncElasticsearch
from redis.asyncio import Redis

from src.core.config import settings
from src.core.logger import LOGGING_CONFIG
from src.main import app


logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def wait_for_es() -> None:
    """Ожидание доступности Elasticsearch."""
    es_client = AsyncElasticsearch(hosts=settings.elastic_url)
    logger.info("Waiting connection to Elasticsearch cluster...")
    while True:
        if await es_client.ping():
            logger.info("Successful connection to Elasticsearch cluster")
            break
        await asyncio.sleep(1)
    await es_client.close()


async def wait_for_redis() -> None:
    """Ожидание доступности Redis."""
    redis_client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=0,
    )
    logger.info("Waiting connection to Redis service...")
    while True:
        if await redis_client.ping():
            logger.info("Successful connection to Redis service")
            break
        await asyncio.sleep(1)
    await redis_client.aclose()


def main() -> None:
    """Запуск приложения."""
    log_level = settings.log_level.lower()
    logger.info("Running application on %s:%s", settings.host, settings.port)
    logger.info("Logging level: %s", log_level)

    # Запускаем асинхронные проверки
    asyncio.run(wait_for_es())
    asyncio.run(wait_for_redis())

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=log_level,
        log_config=LOGGING_CONFIG,
        access_log=True,
    )


if __name__ == "__main__":
    main()

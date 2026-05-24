"""Однократно подключается к RabbitMQ и разворачивает топологию.

Используется как init-контейнер в docker-compose: выполняется до первого
запуска воркеров, чтобы exchanges/queues точно были на месте при первом publish.
"""
import asyncio

from src.core.logging import setup_logging
from src.shared.rabbit import RabbitClient


async def main() -> None:
    logger = setup_logging("bootstrap")
    client = RabbitClient()
    await client.connect()
    try:
        await client.declare_topology()
        logger.info("rabbitmq topology bootstrap done")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

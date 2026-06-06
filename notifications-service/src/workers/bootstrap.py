"""Однократно подключается к RabbitMQ и разворачивает топологию.

Используется как init-контейнер в docker-compose: выполняется до первого
запуска воркеров, чтобы exchanges/queues точно были на месте при первом publish.
"""
import asyncio
import logging

from aio_pika.exceptions import AMQPError

from src.core.logging import setup_logging
from src.shared.rabbit import RabbitClient


CONNECT_RETRIES = 30
CONNECT_RETRY_DELAY_SEC = 2.0


async def _connect_with_retry(client: RabbitClient, logger: logging.Logger) -> None:
    """Ретраит первое подключение: connect_robust(fail_fast) не переподключается,
    а init-контейнер запускается без restart-политики, поэтому защищаемся сами от
    короткого окна, когда нода уже жива, но AMQP-листенер ещё не принимает TCP."""
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            await client.connect()
        except (OSError, AMQPError) as exc:
            if attempt == CONNECT_RETRIES:
                raise
            logger.warning(
                "rabbitmq not ready (attempt %d/%d): %s; retry in %.1fs",
                attempt, CONNECT_RETRIES, exc, CONNECT_RETRY_DELAY_SEC,
            )
            await asyncio.sleep(CONNECT_RETRY_DELAY_SEC)
        else:
            return


async def main() -> None:
    logger = setup_logging("bootstrap")
    client = RabbitClient()
    await _connect_with_retry(client, logger)
    try:
        await client.declare_topology()
        logger.info("rabbitmq topology bootstrap done")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

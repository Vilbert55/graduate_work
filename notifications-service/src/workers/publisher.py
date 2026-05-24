"""Outbox publisher: pending -> RabbitMQ.

Цикл:
  1. Транзакция: claim_messages_batch() — выбирает порцию pending-сообщений
     с SELECT FOR UPDATE SKIP LOCKED и переводит их в 'queued'.
  2. Для каждого — publish в notifications exchange с routing_key = channel.
     Используется publisher_confirms (включено в RabbitClient).
  3. COMMIT транзакции.
  4. asyncio.sleep между батчами — снижение пикового RPS на запись в RabbitMQ.

Гонка между publish и COMMIT: если упадём после publish, но до COMMIT —
строка остаётся 'pending', при следующем тике опубликуем ещё раз -> дубликат
в RabbitMQ. Это безопасно: sender проверит статус в БД и ack без работы.

Гонка между COMMIT и publish: если упадём ПОСЛЕ commit, но до publish —
строка останется 'queued', сообщения в RabbitMQ не будет. Recovery worker
вернёт 'queued' старше N сек обратно в 'pending'.
"""
from __future__ import annotations

import asyncio
import json
import logging

import aio_pika

from src.core.config import settings
from src.core.logging import setup_logging
from src.db.postgres import async_session_maker
from src.shared import notifications_api as napi
from src.shared.messaging import CHANNEL_TO_ROUTING_KEY
from src.shared.rabbit import RabbitClient
from src.shared.worker_loop import install_shutdown_handlers, make_worker_id, run_periodic


logger = logging.getLogger(__name__)


class Publisher:
    def __init__(self) -> None:
        self.rabbit = RabbitClient()
        self.worker_id = make_worker_id("publisher")

    async def setup(self) -> None:
        await self.rabbit.connect()
        await self.rabbit.declare_topology()

    async def shutdown(self) -> None:
        await self.rabbit.close()

    async def iteration(self) -> None:
        if self.rabbit.main_exchange is None:
            raise RuntimeError("RabbitMQ exchange is not set up")

        async with async_session_maker() as session:
            async with session.begin():
                claimed = await napi.claim_messages_batch(
                    session, worker_id=self.worker_id,
                    batch_size=settings.publisher_batch_size,
                )
                if not claimed:
                    return

                for cm in claimed:
                    routing_key = CHANNEL_TO_ROUTING_KEY.get(cm.channel)
                    if routing_key is None:
                        logger.error("unknown channel %s for message %s — skip",
                                     cm.channel, cm.message_id)
                        continue
                    payload = json.dumps({"message_id": str(cm.message_id)}).encode()
                    await self.rabbit.main_exchange.publish(
                        aio_pika.Message(
                            body=payload,
                            content_type="application/json",
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=str(cm.message_id),
                        ),
                        routing_key=routing_key,
                    )

            logger.info("published %d message(s) to RabbitMQ", len(claimed))
        await asyncio.sleep(settings.publisher_sleep_between_batches)


async def main() -> None:
    setup_logging("publisher")
    publisher = Publisher()
    await publisher.setup()
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)
    try:
        await run_periodic(
            name="publisher",
            interval_sec=settings.publisher_interval,
            iteration=publisher.iteration,
            stop_event=stop_event,
        )
    finally:
        await publisher.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

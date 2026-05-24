"""Лёгкая обёртка над aio-pika с автоматическим разворачиванием топологии."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Self

import aio_pika
from aio_pika import ExchangeType

from src.core.config import settings
from src.shared.messaging import (
    EXCHANGE_DLX,
    EXCHANGE_MAIN,
    QUEUE_DEAD,
    QUEUE_EMAIL,
    QUEUE_WS,
    ROUTING_KEY_EMAIL,
    ROUTING_KEY_WS,
)


if TYPE_CHECKING:
    from aio_pika.abc import (
        AbstractRobustChannel,
        AbstractRobustConnection,
        AbstractRobustExchange,
        AbstractRobustQueue,
    )


logger = logging.getLogger(__name__)


class RabbitClient:
    """Robust connection + channel + объявление топологии (идемпотентно)."""

    def __init__(self) -> None:
        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractRobustChannel | None = None
        self.main_exchange: AbstractRobustExchange | None = None
        self.dlx_exchange: AbstractRobustExchange | None = None
        self._queues: dict[str, AbstractRobustQueue] = {}

    async def connect(self) -> Self:
        """Устанавливает соединение и открывает канал."""
        if self.connection is None or self.connection.is_closed:
            self.connection = await aio_pika.connect_robust(settings.rabbit_url)
        if self.channel is None or self.channel.is_closed:
            self.channel = await self.connection.channel(publisher_confirms=True)
            await self.channel.set_qos(prefetch_count=10)
        return self

    async def declare_topology(self) -> None:
        """Идемпотентно объявляет exchanges и очереди."""
        if self.channel is None:
            raise RuntimeError("call connect() before declare_topology()")

        self.main_exchange = await self.channel.declare_exchange(
            EXCHANGE_MAIN, ExchangeType.DIRECT, durable=True,
        )
        self.dlx_exchange = await self.channel.declare_exchange(
            EXCHANGE_DLX, ExchangeType.DIRECT, durable=True,
        )

        # Основные очереди — со ссылкой на DLX.
        common_args: dict[str, Any] = {
            "x-dead-letter-exchange": EXCHANGE_DLX,
        }
        q_email = await self.channel.declare_queue(QUEUE_EMAIL, durable=True, arguments=common_args)
        q_ws = await self.channel.declare_queue(QUEUE_WS, durable=True, arguments=common_args)
        q_dead = await self.channel.declare_queue(QUEUE_DEAD, durable=True)

        await q_email.bind(self.main_exchange, routing_key=ROUTING_KEY_EMAIL)
        await q_ws.bind(self.main_exchange, routing_key=ROUTING_KEY_WS)
        await q_dead.bind(self.dlx_exchange, routing_key=ROUTING_KEY_EMAIL)
        await q_dead.bind(self.dlx_exchange, routing_key=ROUTING_KEY_WS)

        self._queues = {QUEUE_EMAIL: q_email, QUEUE_WS: q_ws, QUEUE_DEAD: q_dead}
        logger.info(
            "RabbitMQ topology declared (exchanges=%s, queues=%s)",
            [EXCHANGE_MAIN, EXCHANGE_DLX], list(self._queues),
        )

    async def close(self) -> None:
        """Закрывает соединение."""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        self.connection = None
        self.channel = None

    def queue(self, name: str) -> AbstractRobustQueue:
        """Возвращает объявленную очередь по имени."""
        if name not in self._queues:
            raise KeyError(f"queue {name!r} is not declared")
        return self._queues[name]

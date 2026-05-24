"""Утилиты для долгоживущих воркеров: периодический цикл с обработкой SIGTERM/SIGINT."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


logger = logging.getLogger(__name__)


def make_worker_id(component: str) -> str:
    """Формирует уникальный идентификатор воркера: component@hostname:pid."""
    return f"{component}@{socket.gethostname()}:{os.getpid()}"


def install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)


async def run_periodic(
    name: str,
    interval_sec: float,
    iteration: Callable[[], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    """Периодически вызывает iteration() с заданным интервалом, пока не выставлен stop_event.

    Исключения внутри iteration() логируются и не останавливают цикл.
    """
    logger.info("worker %s started, interval=%ss", name, interval_sec)
    while not stop_event.is_set():
        try:
            await iteration()
        except Exception:
            logger.exception("worker %s iteration failed", name)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
    logger.info("worker %s stopped", name)

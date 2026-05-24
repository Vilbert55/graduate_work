"""Recovery worker: возвращает «застрявшие» сообщения в pending.

Раз в settings.recovery_interval секунд вызывает SQL-функцию
notifications.requeue_stuck_messages — она сбрасывает статусы
queued (старше queued_stuck_timeout_sec) и sending (старше
sending_stuck_timeout_sec) обратно в pending, чтобы publisher
их перепубликовал.
"""
from __future__ import annotations

import asyncio
import logging

from src.core.config import settings
from src.core.logging import setup_logging
from src.db.postgres import async_session_maker
from src.shared import notifications_api as napi
from src.shared.worker_loop import install_shutdown_handlers, run_periodic


logger = logging.getLogger(__name__)


async def _iteration() -> None:
    """Один прогон recovery: переводит застрявшие сообщения обратно в pending."""
    async with async_session_maker() as session, session.begin():
        n = await napi.requeue_stuck_messages(
            session,
            queued_timeout_sec=settings.queued_stuck_timeout_sec,
            sending_timeout_sec=settings.sending_stuck_timeout_sec,
        )
    if n:
        logger.info("recovery requeued %d message(s)", n)


async def main() -> None:
    """Точка входа recovery worker."""
    setup_logging("recovery")
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)
    await run_periodic(
        name="recovery",
        interval_sec=settings.recovery_interval,
        iteration=_iteration,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    asyncio.run(main())

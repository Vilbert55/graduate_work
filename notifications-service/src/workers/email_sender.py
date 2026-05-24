"""Email sender: consumer для q.email.

Поток обработки одного сообщения:
  1. Получили AMQP-сообщение с message_id в payload.
  2. BEGIN tx -> mark_message_sending(message_id):
       - is_already_sent=TRUE -> ack без работы (дубликат из RabbitMQ).
       - is_dead=TRUE         -> ack без работы (превышен max_attempts).
       - иначе -> status='sending', attempts+=1.
  3. COMMIT tx.
  4. SMTP send (aiosmtplib, Message-ID = message_id).
  5. BEGIN tx -> mark_message_sent(message_id) -> COMMIT -> ack.
  6. При SMTP-ошибке: mark_message_failed:
       - attempts < max_attempts -> status='pending', next_attempt_at = now + backoff
                                   nack(requeue=False) -> DLX -> q.dead.
       - attempts >= max_attempts -> status='dead', ack (сообщение уходит из системы).

Гонка между SMTP-успехом и mark_message_sent: если упадём ровно тут - следующая
попытка увидит status='sending' и attempts уже инкрементированный. Recovery worker
вернёт такое сообщение в pending после sending_stuck_timeout (см. этап 7). Возможен
дубликат отправки - это документированный компромисс; SMTP-провайдер обычно
дедуплицирует по Message-ID.
"""
from __future__ import annotations

import asyncio
import json
import logging
from email.message import EmailMessage
from typing import TYPE_CHECKING
from uuid import UUID

import aiosmtplib

from src.core.config import settings
from src.core.logging import setup_logging
from src.db.postgres import async_session_maker
from src.shared import notifications_api as napi
from src.shared.messaging import QUEUE_EMAIL
from src.shared.rabbit import RabbitClient
from src.shared.worker_loop import install_shutdown_handlers, make_worker_id


if TYPE_CHECKING:
    from aio_pika.abc import AbstractIncomingMessage


logger = logging.getLogger(__name__)

WORKER_ID = make_worker_id("email-sender")


async def _smtp_send(
    *, message_id: UUID, recipient: str, subject: str, body: str, body_format: str,
) -> None:
    """Отправляет письмо через SMTP с Message-ID для дедупликации."""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{message_id}@movies.local>"  # SMTP-провайдер может дедуплицировать повтор;
    if body_format == "html":
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        use_tls=settings.smtp_use_tls,
        start_tls=False,
        timeout=10,
    )


async def _handle(msg: AbstractIncomingMessage) -> None:
    """Обрабатывает одно AMQP-сообщение: проверяет идемпотентность и отправляет письмо."""
    try:
        payload = json.loads(msg.body)
        message_id = UUID(payload["message_id"])
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.exception("malformed message body — drop to DLX")
        await msg.reject(requeue=False)
        return

    # SELECT FOR UPDATE + статус: если already_sent -> ack без отправки (защита от дублей RabbitMQ).
    async with async_session_maker() as session, session.begin():
        payload_db = await napi.mark_message_sending(session, message_id)

    if payload_db.is_already_sent:
        logger.info("dup message_id=%s already sent — ack", message_id)
        await msg.ack()
        return
    if payload_db.is_dead:
        logger.info("dead message_id=%s — ack", message_id)
        await msg.ack()
        return
    if not payload_db.recipient_address:
        logger.error("message_id=%s has no recipient_address — mark failed/dead", message_id)
        async with async_session_maker() as session, session.begin():
            await napi.mark_message_failed(
                session, message_id,
                error="missing recipient_address",
                max_attempts=1,  # сразу в dead
                worker_id=WORKER_ID,
            )
        await msg.ack()
        return

    # Незащищённое окно: падение после SMTP success, до mark_sent -> recovery вернёт в pending -> возможен дубль.
    try:
        await _smtp_send(
            message_id=message_id,
            recipient=payload_db.recipient_address,
            subject=payload_db.subject,
            body=payload_db.body,
            body_format=payload_db.body_format,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SMTP send failed message_id=%s attempt=%d err=%s",
                       message_id, payload_db.attempts, exc)
        async with async_session_maker() as session, session.begin():
            new_status = await napi.mark_message_failed(
                session, message_id,
                error=str(exc)[:1000],
                max_attempts=settings.max_attempts,
                worker_id=WORKER_ID,
            )
        if new_status == "dead":
            # Финал - ack, чтобы покинуть очередь.
            await msg.ack()
        else:
            # pending: следующая попытка через next_attempt_at;
            # отправим в DLX, чтобы не крутить эту очередь.
            await msg.reject(requeue=False)
        return

    # успех
    async with async_session_maker() as session, session.begin():
        await napi.mark_message_sent(session, message_id, worker_id=WORKER_ID)
    logger.info("sent message_id=%s to=%s", message_id, payload_db.recipient_address)
    await msg.ack()


async def main() -> None:
    """Точка входа email sender worker."""
    setup_logging("email-sender")
    rabbit = RabbitClient()
    await rabbit.connect()
    await rabbit.declare_topology()
    queue = rabbit.queue(QUEUE_EMAIL)
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)

    logger.info("email-sender consuming %s as %s", QUEUE_EMAIL, WORKER_ID)
    async with queue.iterator() as it:
        async for msg in it:
            if stop_event.is_set():
                await msg.reject(requeue=True)
                break
            try:
                await _handle(msg)
            except Exception:
                logger.exception("unhandled exception in _handle — reject(requeue=True)")
                # На случай неожиданной ошибки - возвращаем в очередь.
                if not msg.processed:
                    await msg.reject(requeue=True)
    await rabbit.close()


if __name__ == "__main__":
    asyncio.run(main())

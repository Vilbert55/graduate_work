"""WebSocket gateway: consumer для q.ws + WebSocket endpoint.

Реестр коннектов: dict[UUID, set[WebSocket]] — один user_id может
иметь несколько активных вкладок.

При consume:
  1. mark_message_sending.
  2. Если онлайн -> отправить через ws (для каждого активного WS):
        - все успешно -> mark_message_sent + ack;
        - все упали -> mark_message_failed + nack(requeue=False).
  3. Если оффлайн -> mark_message_failed(error='user offline') — строка
     возвращается в 'pending' с next_attempt_at в будущем;
     recovery worker перепубликует.

Аутентификация: JWT через query-параметр token (python-jose).
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from src.core.config import settings
from src.core.logging import setup_logging
from src.db.postgres import async_session_maker
from src.shared import notifications_api as napi
from src.shared.messaging import QUEUE_WS
from src.shared.rabbit import RabbitClient
from src.shared.worker_loop import make_worker_id


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


logger = logging.getLogger(__name__)

WORKER_ID = make_worker_id("ws-gateway")


class ConnectionRegistry:
    """Реестр активных WebSocket-соединений пользователей."""

    def __init__(self) -> None:
        self._conns: dict[UUID, set[WebSocket]] = {}

    def add(self, user_id: UUID, ws: WebSocket) -> None:
        """Регистрирует новое соединение пользователя."""
        self._conns.setdefault(user_id, set()).add(ws)

    def remove(self, user_id: UUID, ws: WebSocket) -> None:
        """Удаляет соединение при отключении клиента."""
        conns = self._conns.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._conns[user_id]

    def get(self, user_id: UUID) -> list[WebSocket]:
        """Возвращает список активных WS-соединений пользователя."""
        return list(self._conns.get(user_id, []))


registry = ConnectionRegistry()


async def _consume_ws_queue(rabbit: RabbitClient, stop_event: asyncio.Event) -> None:
    """Обрабатывает сообщения из очереди q.ws и доставляет их через WebSocket."""
    queue = rabbit.queue(QUEUE_WS)
    async with queue.iterator() as it:
        async for msg in it:
            if stop_event.is_set():
                await msg.reject(requeue=True)
                break
            try:
                data = json.loads(msg.body)
                message_id = UUID(data["message_id"])
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.exception("malformed ws queue message — drop to DLX")
                await msg.reject(requeue=False)
                continue

            # SELECT FOR UPDATE + статус: если already_sent -> ack без отправки (защита от дублей RabbitMQ).
            async with async_session_maker() as session, session.begin():
                payload = await napi.mark_message_sending(session, message_id)

            if payload.is_already_sent or payload.is_dead:
                logger.info("ws skip message_id=%s status=already_sent/dead — ack", message_id)
                await msg.ack()
                continue

            active = registry.get(payload.user_id)
            if not active:
                logger.info("ws user_id=%s is offline, returning to pending", payload.user_id)
                async with async_session_maker() as session, session.begin():
                    await napi.mark_message_failed(
                        session,
                        message_id,
                        error="user offline",
                        max_attempts=settings.max_attempts,
                        worker_id=WORKER_ID,
                    )
                await msg.reject(requeue=False)
                continue

            errors: list[Exception] = []
            for ws in active:
                try:
                    await ws.send_json({
                        "message_id": str(message_id),
                        "subject": payload.subject,
                        "body": payload.body,
                        "body_format": payload.body_format,
                    })
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            if errors and len(errors) == len(active):
                logger.warning(
                    "ws all sockets failed message_id=%s err=%s", message_id, errors[0],
                )
                async with async_session_maker() as session, session.begin():
                    await napi.mark_message_failed(
                        session,
                        message_id,
                        error=str(errors[0])[:500],
                        max_attempts=settings.max_attempts,
                        worker_id=WORKER_ID,
                    )
                await msg.reject(requeue=False)
            else:
                # Незащищённое окно: падение до mark_sent -> recovery вернёт в pending -> возможен дубль WS-уведомления.
                # Клиент может дедуплицировать по message_id в payload самостоятельно.
                async with async_session_maker() as session, session.begin():
                    await napi.mark_message_sent(session, message_id, worker_id=WORKER_ID)
                logger.info("ws sent message_id=%s user_id=%s", message_id, payload.user_id)
                await msg.ack()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Инициализирует RabbitMQ-consumer при старте и завершает при остановке."""
    setup_logging("ws-gateway")
    rabbit = RabbitClient()
    await rabbit.connect()
    await rabbit.declare_topology()
    stop_event = asyncio.Event()
    consumer_task = asyncio.create_task(_consume_ws_queue(rabbit, stop_event))
    yield
    stop_event.set()
    try:
        await asyncio.wait_for(consumer_task, timeout=5.0)
    except TimeoutError:
        logger.warning("ws-gateway consumer shutdown timed out, cancelling")
        consumer_task.cancel()
    await rabbit.close()


app = FastAPI(title="Notifications WS Gateway", lifespan=lifespan)


def _decode_token(token: str) -> UUID:
    """Декодирует JWT и возвращает user_id из поля sub."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return UUID(payload["sub"])


@app.websocket("/notifications/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query(...)) -> None:
    """WebSocket-эндпоинт для in-app уведомлений. Требует JWT в query-параметре token."""
    try:
        user_id = _decode_token(token)
    except (JWTError, KeyError, ValueError):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()
    registry.add(user_id, ws)
    logger.info("ws user_id=%s connected", user_id)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logger.info("ws user_id=%s disconnected", user_id)
    finally:
        registry.remove(user_id, ws)

"""Тонкий Python-фасад над SQL-функциями notifications.*

Каждый метод соответствует одной SQL-функции. Бизнес-логика и идемпотентность —
на стороне БД; этот модуль только сериализует параметры и парсит результаты.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import text


if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ClaimedMessage:
    message_id: UUID
    channel: str


@dataclass(frozen=True, slots=True)
class MessagePayload:
    is_already_sent: bool
    is_dead: bool
    attempts: int
    channel: str
    user_id: UUID
    subject: str
    body: str
    body_format: str
    recipient_address: str | None


async def claim_messages_batch(
    session: AsyncSession,
    worker_id: str,
    batch_size: int,
) -> list[ClaimedMessage]:
    """Атомарно переводит порцию pending-сообщений в queued и возвращает их список."""
    rows = (await session.execute(
        text(
            "SELECT message_id, channel "
            "FROM notifications._claim_messages_batch(:worker_id, :batch_size)"
        ),
        {"worker_id": worker_id, "batch_size": batch_size},
    )).all()
    return [ClaimedMessage(message_id=r.message_id, channel=r.channel) for r in rows]


async def mark_message_sending(
    session: AsyncSession, message_id: UUID,
) -> MessagePayload:
    """Помечает сообщение как 'sending' и возвращает его payload."""
    row = (await session.execute(
        text(
            "SELECT is_already_sent, is_dead, out_attempts, out_channel, out_user_id, "
            "       out_subject, out_body, out_body_format, out_recipient_address "
            "FROM notifications._mark_message_sending(:message_id)"
        ),
        {"message_id": str(message_id)},
    )).one()
    return MessagePayload(
        is_already_sent=row.is_already_sent,
        is_dead=row.is_dead,
        attempts=row.out_attempts,
        channel=row.out_channel,
        user_id=row.out_user_id,
        subject=row.out_subject,
        body=row.out_body,
        body_format=row.out_body_format,
        recipient_address=row.out_recipient_address,
    )


async def mark_message_sent(
    session: AsyncSession, message_id: UUID, worker_id: str | None = None,
) -> None:
    """Помечает сообщение как успешно отправленное."""
    await session.execute(
        text("SELECT notifications._mark_message_sent(:message_id, :worker_id)"),
        {"message_id": str(message_id), "worker_id": worker_id},
    )


async def mark_message_failed(
    session: AsyncSession,
    message_id: UUID,
    error: str,
    max_attempts: int,
    worker_id: str | None = None,
) -> str:
    """Обрабатывает ошибку отправки: pending (retry) или dead (финал).

    Возвращает новый статус сообщения.
    """
    row = (await session.execute(
        text(
            "SELECT notifications._mark_message_failed("
            "    :message_id, :error, :max_attempts, :worker_id"
            ") AS new_status"
        ),
        {
            "message_id": str(message_id),
            "error": error,
            "max_attempts": max_attempts,
            "worker_id": worker_id,
        },
    )).one()
    return row.new_status


async def requeue_stuck_messages(
    session: AsyncSession,
    queued_timeout_sec: int,
    sending_timeout_sec: int,
    worker_id: str = "recovery",
) -> int:
    """Возвращает застрявшие queued/sending сообщения в pending.

    Возвращает количество переведённых сообщений.
    """
    row = (await session.execute(
        text(
            "SELECT notifications._requeue_stuck_messages("
            "    :queued_timeout, :sending_timeout, :worker_id"
            ") AS count"
        ),
        {
            "queued_timeout": queued_timeout_sec,
            "sending_timeout": sending_timeout_sec,
            "worker_id": worker_id,
        },
    )).one()
    return int(row.count)


async def create_task(  # noqa: PLR0913, PLR0917
    session: AsyncSession,
    template_code: str,
    channel: str,
    audience: dict[str, Any],
    name: str | None = None,
    params: dict[str, Any] | None = None,
    cron_expression: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    idempotency_key: str | None = None,
    created_by: str = "admin",
    code: str | None = None,
) -> UUID:
    """Создаёт задание на рассылку уведомлений.

    Возвращает task_id нового или существующего задания (при совпадении idempotency_key).
    code — необязательный человекочитаемый бизнес-ключ задания; задаётся, чтобы потом
    управлять заданием через adm_*_task по code (одноразовым рассылкам не нужен).
    """
    row = (await session.execute(
        text(
            "SELECT notifications.adm_create_task("
            "    :template_code, :channel, CAST(:audience AS jsonb), :name, "
            "    CAST(:params AS jsonb), :cron, :start_at, :end_at, "
            "    :idempotency_key, :created_by, :code"
            ") AS task_id"
        ),
        {
            "template_code": template_code,
            "channel": channel,
            "audience": json.dumps(audience),
            "name": name,
            "params": json.dumps(params or {}),
            "cron": cron_expression,
            "start_at": start_at,
            "end_at": end_at,
            "idempotency_key": idempotency_key,
            "created_by": created_by,
            "code": code,
        },
    )).one()
    return row.task_id

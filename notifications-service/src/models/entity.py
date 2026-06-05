"""SQLAlchemy модели схемы notifications.

ВАЖНО: записи в эти таблицы выполняются ТОЛЬКО через SQL-функции
(notifications.create_task, send_user_event, claim_messages_batch, ...).
Здесь модели нужны для:
  1) автогенерации DDL через alembic;
  2) read-only выборок из воркеров (через v_* представления тоже можно).
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.db.postgres import Base


SCHEMA = "notifications"


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint("code", name="uq_notification_templates_code"),
        {"schema": SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(64), nullable=False)
    name = Column(String(255), nullable=False)
    subject_template = Column(Text, nullable=False)
    body_template = Column(Text, nullable=False)
    body_format = Column(String(16), nullable=False, default="text")  # text | html
    channel = Column(String(16), nullable=False, default="any")        # email | ws | any
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now_utc)
    updated_at = Column(DateTime, nullable=False, default=_now_utc)


class NotificationTask(Base):
    __tablename__ = "notification_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_tasks_idempotency_key"),
        UniqueConstraint("code", name="uq_notification_tasks_code"),
        Index("ix_notification_tasks_next_run", "is_enabled", "next_run_at"),
        {"schema": SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # человекочитаемый бизнес-ключ; NULL у одноразовых/программных рассылок
    code = Column(String(64), nullable=True)
    name = Column(String(255), nullable=False)
    template_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.notification_templates.id"),
        nullable=False,
    )
    channel = Column(String(16), nullable=False)         # email | ws
    audience = Column(JSONB, nullable=False)             # см. формат в SQL-функциях
    params = Column(JSONB, nullable=False, default=dict)  # дополнительный контекст для шаблона

    cron_expression = Column(String(64), nullable=True)  # NULL = одноразовая
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=True)

    is_enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=False)

    created_by = Column(String(64), nullable=False, default="admin")
    idempotency_key = Column(String(128), nullable=True)

    created_at = Column(DateTime, nullable=False, default=_now_utc)
    updated_at = Column(DateTime, nullable=False, default=_now_utc)


class NotificationMessage(Base):
    __tablename__ = "notification_messages"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "user_id", "run_at",
            name="uq_notification_messages_task_user_run",
        ),
        Index("ix_notification_messages_status_attempt", "status", "next_attempt_at"),
        Index("ix_notification_messages_user", "user_id"),
        Index("ix_notification_messages_task", "task_id"),
        {"schema": SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.notification_tasks.id"),
        nullable=False,
    )
    run_at = Column(DateTime, nullable=False)              # конкретная итерация рассылки
    user_id = Column(UUID(as_uuid=True), nullable=False)
    channel = Column(String(16), nullable=False)
    recipient_address = Column(String(255), nullable=True)  # email; для ws не нужен
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    body_format = Column(String(16), nullable=False, default="text")

    # pending -> queued -> sending -> sent | failed | dead
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=_now_utc)
    queued_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)


class WorkerLeaseLog(Base):
    """Сервисная таблица: лог кто что выгрузил в RabbitMQ. Полезна для отладки/наблюдения."""

    __tablename__ = "worker_lease_log"
    __table_args__ = ({"schema": SCHEMA},)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    worker_id = Column(String(128), nullable=False)
    operation = Column(String(64), nullable=False)
    message_id = Column(UUID(as_uuid=True), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now_utc)

"""SQLAlchemy-модели схемы alerting (read-only — модификации через SQL-функции).

Соглашение: таблицы (t_*) меняются ТОЛЬКО через alerting.adm_*-функции,
поэтому ORM-классы здесь используются только для SELECT.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.db.postgres import Base


SCHEMA = "alerting"


class Rule(Base):
    __tablename__ = "t_rules"
    __table_args__ = {"schema": SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(Text, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    sql_query = Column(Text, nullable=False)
    cron_expression = Column(Text, nullable=False)
    template_code = Column(Text, nullable=False)
    channel = Column(Text, nullable=False)
    frequency_cap = Column(JSONB, nullable=False, default=dict)
    max_users = Column(Integer, nullable=False, default=50000)
    is_enabled = Column(Boolean, nullable=False, default=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    status = Column(Text, nullable=False, default="active")
    last_validation_error = Column(Text, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    idempotency_key = Column(Text, nullable=True, unique=True)
    created_by = Column(Text, nullable=False, default="admin")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class Run(Base):
    __tablename__ = "t_runs"
    __table_args__ = {"schema": SCHEMA}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.t_rules.id"), nullable=False)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    matched_users = Column(Integer, nullable=True)
    after_cap_users = Column(Integer, nullable=True)
    dispatched_users = Column(Integer, nullable=True)
    notification_task_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(Text, nullable=False)
    error = Column(Text, nullable=True)


class DispatchHistory(Base):
    """История доставки. На неделе 2 — обычная таблица; партиционирование по
    неделям и retention — задача недели 3 (см. ТЗ §12)."""
    __tablename__ = "t_dispatch_history"
    __table_args__ = (
        PrimaryKeyConstraint("id", "sent_at"),
        {"schema": SCHEMA},
    )

    id = Column(BigInteger, autoincrement=True, nullable=False)
    rule_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    channel = Column(String(16), nullable=False)
    sent_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))

"""Initial schema: tables (t_), SQL functions (adm_/svc_), views, role, seed

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-14

Соглашения об именовании:
  Таблицы:   t_<name>
  Функции:   adm_<name> — для вызова администратором (DBeaver, notification_admin)
             svc_<name> — для вызова только сервисом (Python-воркеры)
  Представления:  v_<name>
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "notifications"
SQL_ROOT = Path(__file__).resolve().parents[2] / "sql"
STATEMENT_SEPARATOR = "-- @statement"


def _load_sql_dir(dir_name: str) -> None:
    """Загружает все .sql файлы из sql/<dir_name>/ в алфавитном порядке."""
    sql_dir = SQL_ROOT / dir_name
    if not sql_dir.exists():
        return
    for path in sorted(sql_dir.glob("*.sql")):
        for stmt in (s.strip() for s in path.read_text(encoding="utf-8").split(STATEMENT_SEPARATOR)):
            if stmt:
                op.execute(stmt)


def upgrade() -> None:
    # gen_random_uuid() доступна в PG 13+, pgcrypto гарантирует наличие функции.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # t_templates — шаблоны уведомлений
    # ------------------------------------------------------------------
    op.create_table(
        "t_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("body_format", sa.String(16), nullable=False, server_default="text"),
        sa.Column("channel", sa.String(16), nullable=False, server_default="any"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.UniqueConstraint("code", name="uq_t_templates_code"),
        sa.CheckConstraint("body_format IN ('text','html')", name="ck_t_templates_body_format"),
        sa.CheckConstraint("channel IN ('email','ws','any')", name="ck_t_templates_channel"),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # t_tasks — задания на рассылку
    # ------------------------------------------------------------------
    op.create_table(
        "t_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.t_templates.id"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("audience", JSONB, nullable=False),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cron_expression", sa.String(64), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="admin"),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.UniqueConstraint("idempotency_key", name="uq_t_tasks_idempotency_key"),
        sa.CheckConstraint("channel IN ('email','ws')", name="ck_t_tasks_channel"),
        sa.CheckConstraint("end_at IS NULL OR end_at > start_at", name="ck_t_tasks_end_after_start"),
        schema=SCHEMA,
    )
    op.create_index("ix_t_tasks_next_run", "t_tasks", ["is_enabled", "next_run_at"], schema=SCHEMA)

    # ------------------------------------------------------------------
    # t_messages — конкретные сообщения (outbox)
    # ------------------------------------------------------------------
    op.create_table(
        "t_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_id", UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.t_tasks.id"), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("recipient_address", sa.String(255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_format", sa.String(16), nullable=False, server_default="text"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("task_id", "user_id", "run_at", name="uq_t_messages_task_user_run"),
        sa.CheckConstraint("channel IN ('email','ws')", name="ck_t_messages_channel"),
        sa.CheckConstraint(
            "status IN ('pending','queued','sending','sent','failed','dead')",
            name="ck_t_messages_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_t_messages_attempts_non_neg"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_t_messages_status_attempt", "t_messages", ["status", "next_attempt_at"], schema=SCHEMA,
    )
    op.create_index("ix_t_messages_user", "t_messages", ["user_id"], schema=SCHEMA)
    op.create_index("ix_t_messages_task", "t_messages", ["task_id"], schema=SCHEMA)

    # ------------------------------------------------------------------
    # t_worker_lease_log — журнал операций воркеров
    # ------------------------------------------------------------------
    op.create_table(
        "t_worker_lease_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("message_id", UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # SQL-объекты: функции, представления, роли, сидинг
    # Порядок важен!
    # ------------------------------------------------------------------
    _load_sql_dir("roles")
    _load_sql_dir("views")
    _load_sql_dir("functions")
    _load_sql_dir("seed")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS notifications.v_messages")
    op.execute("DROP VIEW IF EXISTS notifications.v_tasks")

    op.execute("DROP FUNCTION IF EXISTS notifications.svc_get_messages_for_user(UUID, INT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.svc_requeue_stuck_messages(INT, INT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.svc_mark_message_failed(UUID, TEXT, INT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.svc_mark_message_sent(UUID, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.svc_mark_message_sending(UUID)")
    op.execute("DROP FUNCTION IF EXISTS notifications.svc_claim_messages_batch(TEXT, INT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.svc_send_user_event(UUID, TEXT, TEXT, JSONB, TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.adm_disable_task(UUID)")
    op.execute("DROP FUNCTION IF EXISTS notifications.adm_enable_task(UUID)")
    op.execute("DROP FUNCTION IF EXISTS notifications.adm_update_task(UUID, TEXT, TIMESTAMP, TIMESTAMP, JSONB, JSONB, TEXT, TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.adm_create_task(TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TIMESTAMP, TIMESTAMP, TEXT, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS notifications.adm_upsert_template(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN)")

    op.execute("REVOKE ALL ON SCHEMA notifications FROM notification_admin")
    op.execute("DROP ROLE IF EXISTS notification_admin")

    op.drop_table("t_worker_lease_log", schema=SCHEMA)
    op.drop_index("ix_t_messages_task", table_name="t_messages", schema=SCHEMA)
    op.drop_index("ix_t_messages_user", table_name="t_messages", schema=SCHEMA)
    op.drop_index("ix_t_messages_status_attempt", table_name="t_messages", schema=SCHEMA)
    op.drop_table("t_messages", schema=SCHEMA)
    op.drop_index("ix_t_tasks_next_run", table_name="t_tasks", schema=SCHEMA)
    op.drop_table("t_tasks", schema=SCHEMA)
    op.drop_table("t_templates", schema=SCHEMA)

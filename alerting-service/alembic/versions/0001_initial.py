"""Initial schema: tables (t_*), SQL functions (adm_*), views (v_*), role, seed

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-29

Соглашения об именовании (как в notifications-service):
  Таблицы:        t_<name>      — прямой доступ только у владельца схемы
  Функции:        adm_<name>    — для вызова через роль alerting_admin
  Представления:  v_<name>      — для аналитика
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

SCHEMA = "alerting"
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
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # t_rules — правила
    # ------------------------------------------------------------------
    op.create_table(
        "t_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sql_query", sa.Text(), nullable=False),
        sa.Column("cron_expression", sa.Text(), nullable=False),
        sa.Column("template_code", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("frequency_cap", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("max_users", sa.Integer(), nullable=False, server_default="50000"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_validation_error", sa.Text(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.UniqueConstraint("code", name="uq_t_rules_code"),
        sa.UniqueConstraint("idempotency_key", name="uq_t_rules_idempotency_key"),
        sa.CheckConstraint("channel IN ('email','ws')", name="ck_t_rules_channel"),
        sa.CheckConstraint("status IN ('active','invalid')", name="ck_t_rules_status"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_t_rules_next_run", "t_rules",
        ["is_enabled", "is_deleted", "next_run_at"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # t_runs — история запусков
    # ------------------------------------------------------------------
    op.create_table(
        "t_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", UUID(as_uuid=True),
                  sa.ForeignKey(f"{SCHEMA}.t_rules.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("matched_users", sa.Integer(), nullable=True),
        sa.Column("after_cap_users", sa.Integer(), nullable=True),
        sa.Column("dispatched_users", sa.Integer(), nullable=True),
        sa.Column("notification_task_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','success','failed','skipped')",
            name="ck_t_runs_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_t_runs_rule_started", "t_runs",
        ["rule_id", sa.text("started_at DESC")],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # t_dispatch_history — история доставки (на неделе 2 — без партиций).
    # Партиционирование по неделям + retention 90 дней — задача недели 3
    # (см. diploma_tz.md §12).
    # ------------------------------------------------------------------
    op.create_table(
        "t_dispatch_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("(now() AT TIME ZONE 'utc')")),
        sa.PrimaryKeyConstraint("id", "sent_at", name="pk_t_dispatch_history"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_t_dispatch_user_sent", "t_dispatch_history",
        ["user_id", sa.text("sent_at DESC")],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_t_dispatch_rule_user_sent", "t_dispatch_history",
        ["rule_id", "user_id", sa.text("sent_at DESC")],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------------
    # SQL-объекты: роли, представления, функции, сидинг.
    # Порядок важен: roles → views (зависят от таблиц) → functions → seed.
    # ------------------------------------------------------------------
    _load_sql_dir("roles")
    _load_sql_dir("views")
    _load_sql_dir("functions")
    _load_sql_dir("seed")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS alerting.v_dispatch")
    op.execute("DROP VIEW IF EXISTS alerting.v_runs")
    op.execute("DROP VIEW IF EXISTS alerting.v_rules")

    op.execute("DROP FUNCTION IF EXISTS alerting.adm_trigger_rule(UUID)")
    op.execute("DROP FUNCTION IF EXISTS alerting.adm_dry_run_rule(UUID)")
    op.execute("DROP FUNCTION IF EXISTS alerting.adm_delete_rule(UUID)")
    op.execute("DROP FUNCTION IF EXISTS alerting.adm_disable_rule(UUID)")
    op.execute("DROP FUNCTION IF EXISTS alerting.adm_enable_rule(UUID)")
    op.execute("DROP FUNCTION IF EXISTS alerting.adm_update_rule(UUID, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT)")
    op.execute(
        "DROP FUNCTION IF EXISTS alerting.adm_create_rule(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT, TEXT)"
    )

    op.execute("REVOKE ALL ON SCHEMA alerting FROM alerting_admin")
    op.execute("DROP ROLE IF EXISTS alerting_admin")

    op.drop_index("ix_t_dispatch_rule_user_sent", table_name="t_dispatch_history", schema=SCHEMA)
    op.drop_index("ix_t_dispatch_user_sent", table_name="t_dispatch_history", schema=SCHEMA)
    op.drop_table("t_dispatch_history", schema=SCHEMA)
    op.drop_index("ix_t_runs_rule_started", table_name="t_runs", schema=SCHEMA)
    op.drop_table("t_runs", schema=SCHEMA)
    op.drop_index("ix_t_rules_next_run", table_name="t_rules", schema=SCHEMA)
    op.drop_table("t_rules", schema=SCHEMA)

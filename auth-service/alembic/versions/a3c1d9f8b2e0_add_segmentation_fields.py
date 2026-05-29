"""add segmentation fields to auth.users

Добавляет в auth.users поля gender / age_group / country / is_demo —
используются при построении dim_users в StarRocks (alerting-service)
и сегментации правил рассылки.

Revision ID: a3c1d9f8b2e0
Revises: ffddfa4b92cb
Create Date: 2026-05-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c1d9f8b2e0'
down_revision: Union[str, Sequence[str], None] = 'ffddfa4b92cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('gender', sa.String(length=16), nullable=True),
        schema='auth',
    )
    op.add_column(
        'users',
        sa.Column('age_group', sa.String(length=16), nullable=True),
        schema='auth',
    )
    op.add_column(
        'users',
        sa.Column('country', sa.String(length=2), nullable=True),
        schema='auth',
    )
    op.add_column(
        'users',
        sa.Column(
            'is_demo',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
        schema='auth',
    )


def downgrade() -> None:
    op.drop_column('users', 'is_demo', schema='auth')
    op.drop_column('users', 'country', schema='auth')
    op.drop_column('users', 'age_group', schema='auth')
    op.drop_column('users', 'gender', schema='auth')

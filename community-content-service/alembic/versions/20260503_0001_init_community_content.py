"""init community_content tables

Revision ID: 0001_init_community_content
Revises:
Create Date: 2026-05-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_init_community_content'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCHEMA = 'community_content'


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'bookmarks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('film_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'film_id', name='uq_bookmark_user_film'),
        schema=SCHEMA,
    )
    op.create_index('ix_bookmarks_user_id', 'bookmarks', ['user_id'], schema=SCHEMA)
    op.create_index('ix_bookmarks_film_id', 'bookmarks', ['film_id'], schema=SCHEMA)

    op.create_table(
        'film_likes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('film_id', sa.UUID(), nullable=False),
        sa.Column('score', sa.SmallInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'film_id', name='uq_film_like_user_film'),
        sa.CheckConstraint('score >= 0 AND score <= 10', name='ck_film_like_score_range'),
        schema=SCHEMA,
    )
    op.create_index('ix_film_likes_user_id', 'film_likes', ['user_id'], schema=SCHEMA)
    op.create_index('ix_film_likes_film_id', 'film_likes', ['film_id'], schema=SCHEMA)

    op.create_table(
        'reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('film_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'film_id', name='uq_review_user_film'),
        schema=SCHEMA,
    )
    op.create_index('ix_reviews_user_id', 'reviews', ['user_id'], schema=SCHEMA)
    op.create_index('ix_reviews_film_id', 'reviews', ['film_id'], schema=SCHEMA)
    op.create_index('ix_reviews_created_at', 'reviews', ['created_at'], schema=SCHEMA)

    op.create_table(
        'review_votes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('review_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('score', sa.SmallInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['review_id'],
            [f'{SCHEMA}.reviews.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'review_id', name='uq_review_vote_user_review'),
        sa.CheckConstraint('score IN (-1, 1)', name='ck_review_vote_score_values'),
        schema=SCHEMA,
    )
    op.create_index('ix_review_votes_review_id', 'review_votes', ['review_id'], schema=SCHEMA)
    op.create_index('ix_review_votes_user_id', 'review_votes', ['user_id'], schema=SCHEMA)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('review_votes', schema=SCHEMA)
    op.drop_table('reviews', schema=SCHEMA)
    op.drop_table('film_likes', schema=SCHEMA)
    op.drop_table('bookmarks', schema=SCHEMA)

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.db.postgres import SCHEMA_NAME, Base


def _utcnow() -> datetime:
    """Вернуть текущее время в UTC с tzinfo."""
    return datetime.now(UTC)


class Bookmark(Base):
    """Закладка пользователя на фильм."""

    __tablename__ = 'bookmarks'
    __table_args__ = (
        UniqueConstraint('user_id', 'film_id', name='uq_bookmark_user_film'),
        {'schema': SCHEMA_NAME},
    )

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, nullable=False, index=True)
    film_id = Column(UUID, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class FilmLike(Base):
    """Оценка фильма пользователем (0..10)."""

    __tablename__ = 'film_likes'
    __table_args__ = (
        UniqueConstraint('user_id', 'film_id', name='uq_film_like_user_film'),
        CheckConstraint('score >= 0 AND score <= 10', name='ck_film_like_score_range'),
        {'schema': SCHEMA_NAME},
    )

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, nullable=False, index=True)
    film_id = Column(UUID, nullable=False, index=True)
    score = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class Review(Base):
    """Рецензия пользователя на фильм."""

    __tablename__ = 'reviews'
    __table_args__ = (
        UniqueConstraint('user_id', 'film_id', name='uq_review_user_film'),
        {'schema': SCHEMA_NAME},
    )

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, nullable=False, index=True)
    film_id = Column(UUID, nullable=False, index=True)
    title = Column(String(255), nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    votes = relationship(
        'ReviewVote',
        back_populates='review',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )


class ReviewVote(Base):
    """Голос (лайк/дизлайк) пользователя за рецензию.

    score: 1 = лайк, -1 = дизлайк.
    """

    __tablename__ = 'review_votes'
    __table_args__ = (
        UniqueConstraint('user_id', 'review_id', name='uq_review_vote_user_review'),
        CheckConstraint('score IN (-1, 1)', name='ck_review_vote_score_values'),
        {'schema': SCHEMA_NAME},
    )

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    review_id = Column(
        UUID,
        ForeignKey(f'{SCHEMA_NAME}.reviews.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID, nullable=False, index=True)
    score = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    review = relationship('Review', back_populates='votes')

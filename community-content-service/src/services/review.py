import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement  # noqa: TC002

from src.db.postgres import get_session
from src.models.entity import Review, ReviewVote
from src.schemas.review import ReviewSortField


logger = logging.getLogger(__name__)


# Агрегаты по голосам для использования в select
_LIKES_EXPR = func.coalesce(func.sum(case((ReviewVote.score == 1, 1), else_=0)), 0).label('likes')
_DISLIKES_EXPR = func.coalesce(func.sum(case((ReviewVote.score == -1, 1), else_=0)), 0).label('dislikes')


class ReviewService:
    """Сервис работы с рецензиями и голосами за них."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        user_id: UUID,
        film_id: UUID,
        text: str,
        title: str | None,
    ) -> Review:
        """Создать рецензию; дубликаты на один фильм от одного пользователя запрещены."""
        review = Review(user_id=user_id, film_id=film_id, text=text, title=title)
        self.session.add(review)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            logger.info(f"Review already exists: user={user_id} film={film_id}")
            raise
        await self.session.refresh(review)
        logger.info(f"Review created: id={review.id} user={user_id} film={film_id}")
        return review

    async def update(
        self,
        review_id: UUID,
        user_id: UUID,
        text: str | None,
        title: str | None,
    ) -> Review | None:
        """Обновить рецензию; только автор может изменять."""
        review = await self._get_by_id(review_id)
        if review is None or review.user_id != user_id:
            return None
        if text is not None:
            review.text = text
        if title is not None:
            review.title = title
        await self.session.commit()
        await self.session.refresh(review)
        logger.info(f"Review updated: id={review_id} user={user_id}")
        return review

    async def delete(self, review_id: UUID, user_id: UUID) -> bool:
        """Удалить рецензию автора; вернуть True, если удалено."""
        stmt = delete(Review).where(
            Review.id == review_id,
            Review.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        deleted = result.rowcount > 0
        logger.info(f"Review delete id={review_id} user={user_id} deleted={deleted}")
        return deleted

    async def get(self, review_id: UUID) -> tuple[Review, int, int] | None:
        """Получить рецензию c агрегатами голосов."""
        stmt = (
            select(Review, _LIKES_EXPR, _DISLIKES_EXPR)
            .outerjoin(ReviewVote, ReviewVote.review_id == Review.id)
            .where(Review.id == review_id)
            .group_by(Review.id)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None
        review, likes, dislikes = row
        return review, int(likes), int(dislikes)

    async def list_for_film(
        self,
        film_id: UUID,
        sort: ReviewSortField,
        order_desc: bool,  # noqa: FBT001
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Review, int, int]], int]:
        """Получить список рецензий к фильму с сортировкой и пагинацией."""
        total = await self.session.scalar(
            select(func.count(Review.id)).where(Review.film_id == film_id),
        )

        order_col: ColumnElement
        if sort is ReviewSortField.LIKES:
            order_col = _LIKES_EXPR
        elif sort is ReviewSortField.RATING:
            order_col = (_LIKES_EXPR - _DISLIKES_EXPR).label('rating')
        else:
            order_col = Review.created_at

        order_clause = order_col.desc() if order_desc else order_col.asc()

        stmt = (
            select(Review, _LIKES_EXPR, _DISLIKES_EXPR)
            .outerjoin(ReviewVote, ReviewVote.review_id == Review.id)
            .where(Review.film_id == film_id)
            .group_by(Review.id)
            .order_by(order_clause, Review.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        items: list[tuple[Review, int, int]] = [
            (review, int(likes), int(dislikes)) for review, likes, dislikes in result.all()
        ]
        return items, total or 0

    async def upsert_vote(self, review_id: UUID, user_id: UUID, score: int) -> ReviewVote | None:
        """Выставить/обновить голос пользователя за рецензию (атомарно)."""
        review = await self._get_by_id(review_id)
        if review is None:
            return None

        stmt = (
            insert(ReviewVote)
            .values(review_id=review_id, user_id=user_id, score=score)
            .on_conflict_do_update(
                index_elements=['user_id', 'review_id'],
                set_={'score': score, 'updated_at': func.now()},
            )
            .returning(ReviewVote)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        vote = result.scalar_one()
        logger.info(f"Review vote upserted: review={review_id} user={user_id} score={score}")
        return vote

    async def delete_vote(self, review_id: UUID, user_id: UUID) -> bool:
        """Удалить голос пользователя за рецензию."""
        stmt = delete(ReviewVote).where(
            ReviewVote.review_id == review_id,
            ReviewVote.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        deleted = result.rowcount > 0
        logger.info(f"Review vote delete review={review_id} user={user_id} deleted={deleted}")
        return deleted

    async def _get_by_id(self, review_id: UUID) -> Review | None:
        """Получить рецензию по её ID без агрегатов."""
        stmt = select(Review).where(Review.id == review_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


def get_review_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReviewService:
    """FastAPI-зависимость: экземпляр ReviewService."""
    return ReviewService(session)

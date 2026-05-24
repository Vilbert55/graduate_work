import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.postgres import get_session
from src.models.entity import FilmLike
from src.schemas.like import FilmLikeStats


logger = logging.getLogger(__name__)


class FilmLikeService:
    """Сервис работы с оценками фильмов."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, user_id: UUID, film_id: UUID, score: int) -> FilmLike:
        """Выставить или обновить оценку пользователя для фильма (атомарно)."""
        stmt = (
            insert(FilmLike)
            .values(user_id=user_id, film_id=film_id, score=score)
            .on_conflict_do_update(
                index_elements=['user_id', 'film_id'],
                set_={'score': score, 'updated_at': func.now()},
            )
            .returning(FilmLike)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        like = result.scalar_one()
        logger.info(f"Film like upserted: user={user_id} film={film_id} score={score}")
        return like

    async def remove(self, user_id: UUID, film_id: UUID) -> bool:
        """Удалить оценку; вернуть True, если что-то удалено."""
        stmt = delete(FilmLike).where(
            FilmLike.user_id == user_id,
            FilmLike.film_id == film_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        deleted = result.rowcount > 0
        logger.info(f"Film like delete user={user_id} film={film_id} deleted={deleted}")
        return deleted

    async def get_user_like(self, user_id: UUID, film_id: UUID) -> FilmLike | None:
        """Получить оценку пользователя для фильма (если есть)."""
        return await self._get(user_id, film_id)

    async def get_stats(self, film_id: UUID) -> FilmLikeStats:
        """Собрать агрегированную статистику оценок по фильму."""
        stmt = select(
            func.count(FilmLike.id),
            func.avg(FilmLike.score),
        ).where(FilmLike.film_id == film_id)

        total, average = (await self.session.execute(stmt)).one()

        return FilmLikeStats(
            film_id=film_id,
            total_ratings=total or 0,
            average_score=float(average) if average is not None else None,
        )

    async def _get(self, user_id: UUID, film_id: UUID) -> FilmLike | None:
        """Найти существующую оценку пользователя для фильма."""
        stmt = select(FilmLike).where(
            FilmLike.user_id == user_id,
            FilmLike.film_id == film_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def get_like_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FilmLikeService:
    """FastAPI-зависимость: экземпляр FilmLikeService."""
    return FilmLikeService(session)

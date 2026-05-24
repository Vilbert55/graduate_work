import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.postgres import get_session
from src.models.entity import Bookmark


logger = logging.getLogger(__name__)


class BookmarkService:
    """Сервис работы с закладками пользователя."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_id: UUID, film_id: UUID) -> Bookmark:
        """Добавить закладку; если уже существует — вернуть существующую."""
        bookmark = Bookmark(user_id=user_id, film_id=film_id)
        self.session.add(bookmark)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            logger.info(f"Bookmark already exists for user={user_id} film={film_id}")
            existing = await self._get(user_id, film_id)
            if existing is None:
                raise
            return existing
        await self.session.refresh(bookmark)
        logger.info(f"Bookmark created: user={user_id} film={film_id}")
        return bookmark

    async def remove(self, user_id: UUID, film_id: UUID) -> bool:
        """Удалить закладку; вернуть True, если что-то удалено."""
        stmt = delete(Bookmark).where(
            Bookmark.user_id == user_id,
            Bookmark.film_id == film_id,
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        deleted = result.rowcount > 0
        logger.info(f"Bookmark delete user={user_id} film={film_id} deleted={deleted}")
        return deleted

    async def list_for_user(
        self,
        user_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[Bookmark], int]:
        """Получить список закладок пользователя с пагинацией."""
        total = await self.session.scalar(
            select(func.count(Bookmark.id)).where(Bookmark.user_id == user_id),
        )
        stmt = (
            select(Bookmark)
            .where(Bookmark.user_id == user_id)
            .order_by(Bookmark.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, total or 0

    async def _get(self, user_id: UUID, film_id: UUID) -> Bookmark | None:
        """Найти существующую закладку пользователя на фильм."""
        stmt = select(Bookmark).where(
            Bookmark.user_id == user_id,
            Bookmark.film_id == film_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def get_bookmark_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BookmarkService:
    """FastAPI-зависимость: экземпляр BookmarkService."""
    return BookmarkService(session)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.common import Pagination


class BookmarkCreate(BaseModel):
    """Тело запроса на добавление фильма в закладки."""

    film_id: UUID = Field(..., description='ID фильма')


class BookmarkResponse(BaseModel):
    """Одна закладка."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    film_id: UUID
    created_at: datetime


class BookmarksListResponse(BaseModel):
    """Список закладок пользователя с пагинацией."""

    items: list[BookmarkResponse]
    pagination: Pagination

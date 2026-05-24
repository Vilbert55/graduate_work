from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.common import Pagination


class ReviewSortField(StrEnum):
    """Поля, по которым можно сортировать список рецензий."""

    CREATED_AT = 'created_at'
    LIKES = 'likes'
    RATING = 'rating'


class ReviewCreate(BaseModel):
    """Тело запроса на создание рецензии."""

    film_id: UUID = Field(..., description='ID фильма')
    title: str | None = Field(None, max_length=255, description='Заголовок рецензии')
    text: str = Field(..., min_length=1, description='Текст рецензии')


class ReviewUpdate(BaseModel):
    """Тело запроса на обновление рецензии."""

    title: str | None = Field(None, max_length=255)
    text: str | None = Field(None, min_length=1)


class ReviewResponse(BaseModel):
    """Рецензия с агрегированными данными по голосам."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    film_id: UUID
    title: str | None
    text: str
    created_at: datetime
    updated_at: datetime
    likes: int = 0
    dislikes: int = 0


class ReviewsListResponse(BaseModel):
    """Список рецензий с пагинацией."""

    items: list[ReviewResponse]
    pagination: Pagination


class ReviewVoteUpsert(BaseModel):
    """Тело запроса на голос за рецензию."""

    score: Literal[-1, 1] = Field(..., description='1 = лайк, -1 = дизлайк')


class ReviewVoteResponse(BaseModel):
    """Голос пользователя за рецензию."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    review_id: UUID
    user_id: UUID
    score: int
    created_at: datetime
    updated_at: datetime

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FilmLikeUpsert(BaseModel):
    """Тело запроса на выставление/обновление оценки фильма."""

    score: int = Field(..., ge=0, le=10, description='Оценка от 0 до 10')


class FilmLikeResponse(BaseModel):
    """Оценка фильма конкретным пользователем."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    film_id: UUID
    score: int
    created_at: datetime
    updated_at: datetime


class FilmLikeStats(BaseModel):
    """Статистика оценок по фильму."""

    film_id: UUID
    total_ratings: int = Field(..., description='Общее количество оценок')
    average_score: float | None = Field(..., description='Средняя оценка (None если оценок нет)')

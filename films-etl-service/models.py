from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaseDBModel(BaseModel):
    """Базовая модель для таблиц БД."""
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class FilmWork(BaseDBModel):
    """Модель для таблицы film_work."""
    id: UUID
    title: str
    description: str | None = None
    creation_date: date | None = None
    rating: float | None = None
    type: str
    created: datetime
    modified: datetime


class GenreBase(BaseDBModel):
    id: UUID
    name: str


class Genre(GenreBase):
    """Модель для таблицы genre."""
    description: str | None = None
    created: datetime
    modified: datetime


class Person(BaseDBModel):
    """Модель для таблицы person."""
    id: UUID
    full_name: str
    created: datetime
    modified: datetime


class FilmWorkChange(BaseDBModel):
    """Модель для представления film_work_changes."""
    id: UUID
    title: str
    changed: datetime


class PersonRole(BaseDBModel):
    """Модель для персоны с ролью."""
    id: UUID
    name: str


class FilmData(BaseDBModel):
    """Полные данные о фильме."""
    id: UUID
    title: str
    description: str | None = None
    imdb_rating: float | None
    genres: list[GenreBase] = Field(default_factory=list)
    directors: list[PersonRole] = Field(default_factory=list)
    actors: list[PersonRole] = Field(default_factory=list)
    writers: list[PersonRole] = Field(default_factory=list)

    directors_names: list[str] = Field(default_factory=list)
    actors_names: list[str] = Field(default_factory=list)
    writers_names: list[str] = Field(default_factory=list)


class StateData(BaseDBModel):
    """Модель для состояния ETL процесса."""
    extract_dttm_current: datetime | None = None
    extract_dttm_last: datetime | None = None
    offset: int = 0

    def to_storage(self) -> dict[str, Any]:
        """Конвертация в формат для хранения."""
        return self.model_dump(mode="json")

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> "StateData":
        """Создание из данных хранилища."""
        return cls(**data)

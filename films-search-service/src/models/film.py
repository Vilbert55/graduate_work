from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.elastic_query import (
    GenreFilterQuery,
    MatchAllQuery,
    SearchQuery,
    SimilarFilmsQuery,
)


# Базовые модели данных
class Genre(BaseModel):
    """Модель жанра."""
    uuid: UUID
    name: str


class Person(BaseModel):
    """Модель персоны (актёр, режиссёр, сценарист)."""
    uuid: UUID
    full_name: str


class FilmShort(BaseModel):
    """Краткая информация о фильме для списков."""
    uuid: UUID
    title: str
    imdb_rating: float | None = Field(None, ge=0, le=10)

    model_config = ConfigDict(from_attributes=True)


class FilmDetail(FilmShort):
    """Полная информация о фильме."""
    description: str | None = None
    genres: list[Genre] = Field(default_factory=list)
    actors: list[Person] = Field(default_factory=list)
    writers: list[Person] = Field(default_factory=list)
    directors: list[Person] = Field(default_factory=list)


# Модели ответов API (наследуемся от базовых моделей)
class FilmShortResponse(FilmShort):
    """Краткая информация о фильме для списков (ответ API)."""
    @classmethod
    def from_film_short(cls, film: FilmShort) -> "FilmShortResponse":
        """Создать FilmShortResponse из FilmShort."""
        return cls.model_validate(film.model_dump())


class FilmDetailResponse(FilmDetail):
    """Полная информация о фильме (ответ API)."""
    @classmethod
    def from_film_detail(cls, film: FilmDetail) -> "FilmDetailResponse":
        """Создать FilmDetailResponse из FilmDetail."""
        return cls.model_validate(film.model_dump())


class FilmsListResponse(BaseModel):
    """Список фильмов с пагинацией (ответ API)."""
    films: list[FilmShortResponse]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_pages: int = Field(ge=0)


# Модели для создания запросов
class ElasticsearchQueryBuilder:
    """Фасад для создания запросов Elasticsearch."""

    @staticmethod
    def build_search_query(
        query: str,
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Построить запрос для поиска фильмов."""
        search_query = SearchQuery(
            query=query,
            page_number=page_number,
            page_size=page_size,
        )
        return search_query.build()

    @staticmethod
    def build_films_query(
        genre_id: UUID | None = None,
        sort: str = "-imdb_rating",
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Построить запрос для получения списка фильмов."""
        if genre_id:
            genre_query = GenreFilterQuery(
                genre_id=genre_id,
                sort=sort,
                page_number=page_number,
                page_size=page_size,
            )
            return genre_query.build()

        match_all_query = MatchAllQuery(
            sort=sort,
            page_number=page_number,
            page_size=page_size,
        )
        return match_all_query.build()

    @staticmethod
    def build_similar_films_query(
        film_id: UUID,
        genre_ids: list[UUID],
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Построить запрос для получения похожих фильмов."""
        similar_query = SimilarFilmsQuery(
            film_id=film_id,
            genre_ids=genre_ids,
            page_number=page_number,
            page_size=page_size,
        )
        return similar_query.build()

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class BaseElasticQuery(ABC):
    """Базовый класс для всех запросов Elasticsearch."""

    def __init__(
        self,
        page_number: int = 1,
        page_size: int = 50,
        sort: str | None = None,
    ) -> None:
        """
        Инициализация базового запроса.

        Args:
            page_number: Номер страницы (начинается с 1)
            page_size: Размер страницы
            sort: Параметры сортировки
        """
        self.page_number = page_number
        self.page_size = page_size
        self.sort = sort

    @property
    def from_(self) -> int:
        """Вычисляемое смещение для пагинации в Elasticsearch."""
        return (self.page_number - 1) * self.page_size

    @abstractmethod
    def _build_query_body(self) -> dict[str, Any]:
        """
        Построить тело запроса. Должен быть реализован в подклассах.

        Returns:
            dict: Тело запроса Elasticsearch (верхнеуровневый каркас)
        """

    def _build_sort(self) -> list[dict]:
        """
        Построить параметры сортировки.

        Returns:
            list: Список словарей с параметрами сортировки
        """
        if not self.sort:
            return []

        if self.sort.startswith("-"):
            field = self.sort[1:]
            order = "desc"
        elif self.sort.startswith("+"):
            field = self.sort[1:]
            order = "asc"
        else:
            field = self.sort
            order = "asc"

        return [{field: {"order": order}}]

    def build(self) -> dict[str, Any]:
        """
        Построить полный запрос для Elasticsearch.

        Returns:
            dict: Полный запрос с пагинацией, сортировкой и фильтрацией
        """
        body = {
            "from": self.from_,
            "size": self.page_size,
        }

        query_body = self._build_query_body()
        if query_body:
            body["query"] = query_body

        sort_body = self._build_sort()
        if sort_body:
            body["sort"] = sort_body

        return body


class MatchAllQuery(BaseElasticQuery):
    """Запрос для получения всех документов (с возможной фильтрацией)."""

    @staticmethod
    def _build_query_body() -> dict[str, Any]:
        """Построить запрос match_all для Elasticsearch.

        Returns:
            dict: Тело запроса Elasticsearch (верхнеуровневый каркас)
        """
        return {"match_all": {}}


class SearchQuery(BaseElasticQuery):
    """Запрос для полнотекстового поиска."""

    def __init__(
        self,
        query: str,
        fields: list[str] | None = None,
        **kwargs,
    ) -> None:
        """
        Инициализация поискового запроса.

        Args:
            query: Текст для поиска
            fields: Поля для поиска (по умолчанию: основные поля фильмов)
            **kwargs: Дополнительные параметры базового запроса
        """
        super().__init__(**kwargs)
        self.query = query
        self.fields = fields or [
            "title^3",
            "description",
            "actors_names",
            "writers_names",
            "directors_names",
        ]

    def _build_query_body(self) -> dict[str, Any]:
        """Построить multi_match запрос для полнотекстового поиска.

        Returns:
            dict: Тело запроса Elasticsearch (верхнеуровневый каркас)
        """
        return {
            "multi_match": {
                "query": self.query,
                "fields": self.fields,
                "fuzziness": "AUTO",
            },
        }

    @staticmethod
    def _build_sort() -> list[dict]:
        """Для поиска всегда сортируем по релевантности.

        Returns:
            list: Список словарей с параметрами сортировки"""
        return [{"_score": {"order": "desc"}}]


class FilteredQuery(MatchAllQuery):
    """Запрос с фильтрацией."""

    @abstractmethod
    def _build_filters(self) -> list[dict[str, Any]]:
        """
        Построить фильтры. Должен быть реализован в подклассах.

        Returns:
            list: Список фильтров для Elasticsearch
        """

    def _build_query_body(self) -> dict[str, Any]:
        """Построить bool запрос с фильтрами.
        Returns:
            dict: Тело запроса Elasticsearch (верхнеуровневый каркас)
        """
        filters = self._build_filters()

        if not filters:
            return super()._build_query_body()

        return {
            "bool": {
                "filter": filters,
            },
        }


class GenreFilterQuery(FilteredQuery):
    """Запрос с фильтрацией по жанру."""

    def __init__(self, genre_id: UUID, **kwargs) -> None:
        """
        Инициализация запроса с фильтром по жанру.

        Args:
            genre_id: UUID жанра для фильтрации
            **kwargs: Дополнительные параметры базового запроса
        """
        super().__init__(**kwargs)
        self.genre_id = genre_id

    def _build_filters(self) -> list[dict[str, Any]]:
        """Построить nested фильтр по жанрам.
        Returns:
            list: Список словарей с параметрами сортировки о жанру
        """
        return [
            {
                "nested": {
                    "path": "genres",
                    "query": {
                        "term": {"genres.id": str(self.genre_id)},
                    },
                },
            },
        ]


class SimilarFilmsQuery(BaseElasticQuery):
    """Запрос для поиска похожих фильмов."""

    def __init__(
        self,
        film_id: UUID,
        genre_ids: list[UUID],
        **kwargs,
    ) -> None:
        """
        Инициализация запроса для похожих фильмов.

        Args:
            film_id: UUID фильма для исключения из результатов
            genre_ids: Список UUID жанров для фильтрации
            **kwargs: Дополнительные параметры базового запроса
        """
        super().__init__(**kwargs)
        self.film_id = film_id
        self.genre_ids = genre_ids

    def _build_query_body(self) -> dict[str, Any]:
        """Построить bool запрос для поиска похожих фильмов.
        Returns:
            dict: Тело запроса Elasticsearch (верхнеуровневый каркас)
        """
        return {
            "bool": {
                "must_not": [{"term": {"_id": str(self.film_id)}}],
                "filter": [
                    {
                        "nested": {
                            "path": "genres",
                            "query": {
                                "terms": {"genres.id": [str(gid) for gid in self.genre_ids]},
                            },
                        },
                    },
                ],
            },
        }

    @staticmethod
    def _build_sort() -> list[dict]:
        """Переопределяем сортировку для похожих фильмов по рейтингу.
        Returns:
            list: Список словарей с параметрами сортировки по рейтингу"""
        return [{"imdb_rating": {"order": "desc"}}]

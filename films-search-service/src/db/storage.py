from abc import ABC, abstractmethod
from uuid import UUID

from elasticsearch import NotFoundError
from opentelemetry import trace  # <-- импортируем trace

from src.db.elastic import AsyncElasticsearch
from src.models.film import ElasticsearchQueryBuilder, FilmDetail, FilmShort, Genre, Person


# Получаем трейсер для текущего модуля
tracer = trace.get_tracer(__name__)


class FilmStorage(ABC):
    """Абстрактный класс для хранилища фильмов."""

    @abstractmethod
    async def get_by_id(self, film_id: str) -> FilmDetail | None:
        """Получить фильм по ID."""

    @abstractmethod
    async def search(
        self,
        query: str,
        page_number: int,
        page_size: int,
    ) -> tuple[list[FilmShort], int]:
        """Полнотекстовый поиск фильмов."""

    @abstractmethod
    async def get_list(
        self,
        genre_id: UUID | None,
        sort: str,
        page_number: int,
        page_size: int,
    ) -> tuple[list[FilmShort], int]:
        """Получить список фильмов с фильтрацией и сортировкой."""

    @abstractmethod
    async def get_similar(
        self,
        film_id: UUID,
        genre_ids: list[UUID],
        page_number: int,
        page_size: int,
    ) -> tuple[list[FilmShort], int]:
        """Получить похожие фильмы."""


class ElasticFilmStorage(FilmStorage):
    """Реализация хранилища фильмов в Elasticsearch."""

    def __init__(self, elastic_client: AsyncElasticsearch) -> None:
        self._elastic = elastic_client
        self._index = "movies"

    async def get_by_id(self, film_id: str) -> FilmDetail | None:
        with tracer.start_as_current_span("elasticsearch.get") as span:
            span.set_attribute("db.system", "elasticsearch")
            span.set_attribute("db.operation", "get")
            span.set_attribute("db.elasticsearch.index", self._index)
            span.set_attribute("db.elasticsearch.id", film_id)

            try:
                doc = await self._elastic.get(index=self._index, id=film_id)
                span.set_attribute("db.elasticsearch.found", True)  # noqa: FBT003
            except NotFoundError:
                span.set_attribute("db.elasticsearch.found", False)  # noqa: FBT003
                return None

            source: dict = doc["_source"]
            return FilmDetail(
                uuid=UUID(source["id"]),
                title=source["title"],
                imdb_rating=source.get("imdb_rating"),
                description=source.get("description"),
                genres=[
                    Genre(uuid=UUID(genre["id"]), name=genre["name"])
                    for genre in source.get("genres", [])
                ],
                actors=[
                    Person(uuid=UUID(person["id"]), full_name=person["name"])
                    for person in source.get("actors", [])
                ],
                writers=[
                    Person(uuid=UUID(person["id"]), full_name=person["name"])
                    for person in source.get("writers", [])
                ],
                directors=[
                    Person(uuid=UUID(person["id"]), full_name=person["name"])
                    for person in source.get("directors", [])
                ],
            )

    async def search(
        self,
        query: str,
        page_number: int,
        page_size: int,
    ) -> tuple[list[FilmShort], int]:
        body = ElasticsearchQueryBuilder.build_search_query(
            query=query,
            page_number=page_number,
            page_size=page_size,
        )
        # Передаём дополнительную информацию о запросе в _execute_search
        return await self._execute_search(body, operation="search", query=query)

    async def get_list(
        self,
        genre_id: UUID | None,
        sort: str,
        page_number: int,
        page_size: int,
    ) -> tuple[list[FilmShort], int]:
        body = ElasticsearchQueryBuilder.build_films_query(
            genre_id=genre_id,
            sort=sort,
            page_number=page_number,
            page_size=page_size,
        )
        operation = "list"
        if genre_id:
            operation = "list_filtered"
        return await self._execute_search(body, operation=operation, genre_id=genre_id, sort=sort)

    async def get_similar(
        self,
        film_id: UUID,
        genre_ids: list[UUID],
        page_number: int,
        page_size: int,
    ) -> tuple[list[FilmShort], int]:
        body = ElasticsearchQueryBuilder.build_similar_films_query(
            film_id=film_id,
            genre_ids=genre_ids,
            page_number=page_number,
            page_size=page_size,
        )
        return await self._execute_search(
            body, operation="similar", film_id=film_id, genre_ids=genre_ids,
        )

    async def _execute_search(self, body: dict, **attrs) -> tuple[list[FilmShort], int]:
        # Дочерний спан для поискового запроса
        with tracer.start_as_current_span("elasticsearch.search") as span:
            span.set_attribute("db.system", "elasticsearch")
            span.set_attribute("db.operation", "search")
            span.set_attribute("db.elasticsearch.index", self._index)
            # Атрибуты, переданные через attrs (например, query, genre_id)
            for key, value in attrs.items():
                if value is not None:
                    span.set_attribute(f"db.elasticsearch.{key}", str(value))

            response = await self._elastic.search(index=self._index, body=body)
            total = response["hits"]["total"]["value"]
            span.set_attribute("db.elasticsearch.hits.total", total)

            films = []
            for hit in response["hits"]["hits"]:
                source: dict = hit["_source"]
                films.append(FilmShort(
                    uuid=UUID(source["id"]),
                    title=source["title"],
                    imdb_rating=source.get("imdb_rating"),
                ))
            return films, total

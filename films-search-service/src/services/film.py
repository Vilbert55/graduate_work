from functools import lru_cache
from uuid import UUID

from fastapi import Request
from opentelemetry import trace  # <-- импортируем trace

from src.db.cache import Cache, RedisCache
from src.db.storage import ElasticFilmStorage, FilmStorage
from src.models.film import FilmDetail, FilmShort


FILM_CACHE_EXPIRE = 60 * 5  # 5 минут

tracer = trace.get_tracer(__name__)


class FilmService:
    def __init__(self, cache: Cache, storage: FilmStorage) -> None:
        self._cache = cache
        self._storage = storage

    async def get_by_id(self, film_id: str) -> FilmDetail | None:
        cache_key = f"film_work:{film_id}"

        # Пытаемся получить из кэша
        with tracer.start_as_current_span("cache.get") as span:
            span.set_attribute("db.system", "redis")
            span.set_attribute("db.operation", "get")
            span.set_attribute("db.redis.key", cache_key)

            cached = await self._cache.get(cache_key)
            span.set_attribute("cache.hit", cached is not None)

            if cached:
                return FilmDetail.model_validate_json(cached)

        # Если нет в кэше, идём в storage
        film = await self._storage.get_by_id(film_id)

        # Сохраняем в кэш
        if film:
            with tracer.start_as_current_span("cache.set") as span:
                span.set_attribute("db.system", "redis")
                span.set_attribute("db.operation", "set")
                span.set_attribute("db.redis.key", cache_key)
                await self._cache.set(cache_key, film.model_dump_json(), FILM_CACHE_EXPIRE)

        return film

    async def search_films(
        self,
        query: str,
        page_number: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FilmShort], int]:
        return await self._storage.search(query, page_number, page_size)

    async def get_films_list(
        self,
        genre_id: UUID | None = None,
        sort: str = "-imdb_rating",
        page_number: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FilmShort], int]:
        return await self._storage.get_list(genre_id, sort, page_number, page_size)

    async def get_similar_films(
        self,
        film_id: UUID,
        page_number: int = 1,
        page_size: int = 50,
    ) -> tuple[list[FilmShort], int]:
        film = await self.get_by_id(str(film_id))
        if not film or not film.genres:
            return [], 0
        genre_ids = [g.uuid for g in film.genres]
        return await self._storage.get_similar(film_id, genre_ids, page_number, page_size)


@lru_cache
def get_film_service(request: Request) -> FilmService:
    redis_client = request.app.state.redis
    elastic_client = request.app.state.elastic
    cache = RedisCache(redis_client)
    storage = ElasticFilmStorage(elastic_client)
    return FilmService(cache=cache, storage=storage)

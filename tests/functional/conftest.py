import uuid
from typing import Any

import pytest
import pytest_asyncio
import redis.asyncio as redis
from aiohttp import ClientSession
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from settings import test_settings


@pytest_asyncio.fixture(scope='session')
async def client_session():
    session = ClientSession()
    yield session
    await session.close()


@pytest_asyncio.fixture(name='es_client', scope='session')
async def es_client():
    client = AsyncElasticsearch(hosts=test_settings.elastic_url, verify_certs=False)
    yield client
    await client.close()


@pytest_asyncio.fixture(name='redis_client', scope='session')
async def redis_client():
    client = redis.Redis(
        host=test_settings.redis_host,
        port=test_settings.redis_port,
        db=0,
        decode_responses=True,
    )
    yield client
    await client.aclose()


def make_film_source(
    *,
    film_id: str | None = None,
    title: str = "Default Title",
    imdb_rating: float = 0.0,
    description: str = "Default description",
    genres: list[dict] | None = None,
    actors: list[dict] | None = None,
    writers: list[dict] | None = None,
    directors: list[dict] | None = None,
    **extra_fields,
) -> dict[str, Any]:
    """
    Создаёт словарь _source для фильма со стандартными полями.
    Можно переопределить любое поле через аргументы.
    """
    if film_id is None:
        film_id = str(uuid.uuid4())

    # Значения по умолчанию
    if genres is None:
        genres = []
    if actors is None:
        actors = []
    if writers is None:
        writers = []
    if directors is None:
        directors = []

    source = {
        "id": film_id,
        "title": title,
        "imdb_rating": imdb_rating,
        "description": description,
        "genres": genres,
        "actors": actors,
        "writers": writers,
        "directors": directors,
        "actors_names": [a["name"] for a in actors],
        "writers_names": [w["name"] for w in writers],
        "directors_names": [d["name"] for d in directors],
    }
    # Добавляем возможные дополнительные поля
    source.update(extra_fields)
    return source


def make_es_bulk_item(source: dict[str, Any]) -> dict[str, Any]:
    """Оборачивает source в формат для bulk-записи в Elasticsearch."""
    return {
        "_index": test_settings.es_index,
        "_id": source["id"],
        "_source": source,
    }


# ---------- Фикстуры данных ----------
@pytest.fixture
def es_bulk_data() -> list[dict]:
    """60 фильмов с фиксированными полями"""
    data = []
    for _ in range(60):
        film_id = str(uuid.uuid4())
        source = make_film_source(
            film_id=film_id,
            title="The Star",
            imdb_rating=8.5,
            description="New World",
            genres=[
                {"id": str(uuid.uuid4()), "name": "Action"},
                {"id": str(uuid.uuid4()), "name": "Sci-Fi"},
            ],
            actors=[
                {"id": str(uuid.uuid4()), "name": "Ann"},
                {"id": str(uuid.uuid4()), "name": "Bob"},
            ],
            writers=[
                {"id": str(uuid.uuid4()), "name": "Ben"},
                {"id": str(uuid.uuid4()), "name": "Howard"},
            ],
            directors=[
                {"id": str(uuid.uuid4()), "name": "Stan"},
            ],
        )
        data.append(make_es_bulk_item(source))
    return data


@pytest.fixture
def film_full_data() -> list[dict]:
    """
    Один фильм со всеми заполненными полями (для тестов деталей и кеша).
    """
    film_id = str(uuid.uuid4())
    genre_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())
    writer_id = str(uuid.uuid4())
    director_id = str(uuid.uuid4())

    source = make_film_source(
        film_id=film_id,
        title="Detailed Movie",
        imdb_rating=9.5,
        description="A very detailed description",
        genres=[{"id": genre_id, "name": "Drama"}],
        actors=[{"id": actor_id, "name": "John Doe"}],
        writers=[{"id": writer_id, "name": "Jane Smith"}],
        directors=[{"id": director_id, "name": "Director Name"}],
    )
    return [make_es_bulk_item(source)]


@pytest.fixture
def films_data_for_pagination() -> list[dict]:
    """65 фильмов с разными названиями для тестов пагинации."""
    data = []
    for i in range(65):
        film_id = str(uuid.uuid4())
        source = make_film_source(
            film_id=film_id,
            title=f"Movie {i}",
            imdb_rating=round(i % 10, 1),
            description="description",
            genres=[{"id": str(uuid.uuid4()), "name": "Action"}],
        )
        data.append(make_es_bulk_item(source))
    return data


@pytest.fixture
def films_data_for_search() -> list[dict]:
    """Набор фильмов с разными названиями для тестов поиска."""
    movies = [
        {"title": "Star Wars: A New Hope", "rating": 8.6},
        {"title": "Star Trek", "rating": 7.9},
        {"title": "The Empire Strikes Back", "rating": 8.7},
        {"title": "Interstellar", "rating": 8.6},
    ]
    data = []
    for m in movies:
        film_id = str(uuid.uuid4())
        source = make_film_source(
            film_id=film_id,
            title=m["title"],
            imdb_rating=m["rating"],
            description="desc",
        )
        data.append(make_es_bulk_item(source))
    return data


@pytest.fixture
def films_data_for_filter() -> list[dict]:
    """Фильмы с разными жанрами и рейтингами для тестов фильтрации/сортировки."""
    genre_action_id = str(uuid.uuid4())
    genre_comedy_id = str(uuid.uuid4())
    movies = [
        {"title": "Action High", "rating": 9.5, "genre_id": genre_action_id, "genre_name": "Action"},
        {"title": "Action Medium", "rating": 7.5, "genre_id": genre_action_id, "genre_name": "Action"},
        {"title": "Action Low", "rating": 5.0, "genre_id": genre_action_id, "genre_name": "Action"},
        {"title": "Comedy Best", "rating": 8.8, "genre_id": genre_comedy_id, "genre_name": "Comedy"},
        {"title": "Comedy Ok", "rating": 6.5, "genre_id": genre_comedy_id, "genre_name": "Comedy"},
    ]
    data = []
    for m in movies:
        film_id = str(uuid.uuid4())
        source = make_film_source(
            film_id=film_id,
            title=m["title"],
            imdb_rating=m["rating"],
            description="desc",
            genres=[{"id": m["genre_id"], "name": m["genre_name"]}],
        )
        data.append(make_es_bulk_item(source))
    return data


@pytest_asyncio.fixture(name='es_write_data')
def es_write_data(es_client: AsyncElasticsearch):
    async def inner(data: list[dict]):
        # Удаляем индекс, если существует, и создаём заново
        if await es_client.indices.exists(index=test_settings.es_index):
            await es_client.indices.delete(index=test_settings.es_index)
        await es_client.indices.create(
            index=test_settings.es_index,
            body=test_settings.es_schema,
        )

        # Записываем данные
        _, errors = await async_bulk(client=es_client, actions=data, refresh='wait_for')
        if errors:
            raise Exception(f'Ошибки записи данных в Elasticsearch: {errors}')

    return inner


@pytest_asyncio.fixture
def make_get_request(client_session: ClientSession):
    async def inner(endpoint: str, query_data: dict | None = None):
        url = test_settings.service_url + endpoint
        params = query_data or {}
        async with client_session.get(url, params=params) as response:
            body = await response.json()
            return body, response.status
    return inner

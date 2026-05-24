# ruff: noqa: ANN201, ANN001, S101, PLR2004
import uuid

import pytest
from redis.asyncio import Redis


pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_film_detail_validation(make_get_request):
    """Валидация UUID и обработка отсутствующего фильма."""
    # Невалидный UUID
    _body, status = await make_get_request('/films-search/api/v1/films/invalid-uuid', {})
    assert status == 422

    # Несуществующий UUID
    random_uuid = str(uuid.uuid4())
    _body, status = await make_get_request(f'/films-search/api/v1/films/{random_uuid}', {})
    assert status == 404


async def test_film_detail_success(make_get_request, es_write_data, film_full_data):
    """Получение детальной информации о конкретном фильме."""
    await es_write_data(film_full_data)
    movie_id = film_full_data[0]['_id']

    body, status = await make_get_request(f'/films-search/api/v1/films/{movie_id}', {})
    assert status == 200
    assert body['uuid'] == movie_id
    assert body['title'] == 'Detailed Movie'
    assert body['imdb_rating'] == 9.5
    assert body['description'] == 'A very detailed description'
    assert len(body['genres']) == 1
    assert body['genres'][0]['name'] == 'Drama'
    assert body['actors'][0]['full_name'] == 'John Doe'
    assert body['writers'][0]['full_name'] == 'Jane Smith'
    assert body['directors'][0]['full_name'] == 'Director Name'


async def test_film_detail_cache(make_get_request, es_write_data, film_full_data, redis_client: Redis):
    """Проверка кеширования детальной информации о фильме."""
    await redis_client.flushdb()
    await es_write_data(film_full_data)
    movie_id = film_full_data[0]['_id']

    # Первый запрос (кеш промах)
    body1, status1 = await make_get_request(f'/films-search/api/v1/films/{movie_id}', {})
    assert status1 == 200

    # Второй – из кеша middleware
    body2, status2 = await make_get_request(f'/films-search/api/v1/films/{movie_id}', {})
    assert status2 == 200
    assert body1 == body2

    # Удаляем ключ кеша сервиса
    service_cache_key = f"film_work:{movie_id}"
    await redis_client.delete(service_cache_key)

    # Третий запрос с фиктивным параметром, чтобы обойти middleware кеш
    # (параметр игнорируется сервисом, но меняет ключ middleware)
    body3, status3 = await make_get_request(f'/films-search/api/v1/films/{movie_id}', {'cache_bypass': '1'})
    assert status3 == 200
    assert body3 == body1

    # Ключ сервиса должен восстановиться
    assert await redis_client.exists(service_cache_key) == 1

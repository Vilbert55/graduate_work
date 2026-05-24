# ruff: noqa: ANN201, ANN001, S101, PLR2004
import asyncio

import pytest
from redis.asyncio import Redis


pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_films_list_validation(make_get_request):
    """Валидация параметров списка фильмов."""
    # page_number < 1
    _body, status = await make_get_request('/films-search/api/v1/films/', {'page_number': 0})
    assert status == 422

    # page_size < 1
    _body, status = await make_get_request('/films-search/api/v1/films/', {'page_size': 0})
    assert status == 422

    # page_size > 100
    _body, status = await make_get_request('/films-search/api/v1/films/', {'page_size': 101})
    assert status == 422

    # genre с невалидным UUID
    _body, status = await make_get_request('/films-search/api/v1/films/', {'genre': 'invalid-uuid'})
    assert status == 422


async def test_films_list_pagination(make_get_request, es_write_data, films_data_for_pagination):
    """Проверка пагинации в списке всех фильмов."""
    await es_write_data(films_data_for_pagination)

    # Страница 1, size=20
    body, status = await make_get_request('/films-search/api/v1/films/', {'page_size': 20, 'page_number': 1})
    assert status == 200
    assert len(body['films']) == 20
    assert body['total'] == 65
    assert body['page'] == 1
    assert body['page_size'] == 20
    assert body['total_pages'] == 4

    # Последняя страница
    body, status = await make_get_request('/films-search/api/v1/films/', {'page_size': 20, 'page_number': 4})
    assert status == 200
    assert len(body['films']) == 5  # 65 - 20*3 = 5

    # За пределами
    body, status = await make_get_request('/films-search/api/v1/films/', {'page_size': 20, 'page_number': 5})
    assert status == 200
    assert len(body['films']) == 0


async def test_films_list_filter_sort(make_get_request, es_write_data, films_data_for_filter):
    """Фильтрация по жанру и сортировка."""
    await es_write_data(films_data_for_filter)

    # Извлекаем genre_id из первого элемента (Action)
    genre_action_id = films_data_for_filter[0]['_source']['genres'][0]['id']

    # Фильтр по жанру Action
    body, status = await make_get_request('/films-search/api/v1/films/', {'genre': genre_action_id, 'page_size': 10})
    assert status == 200
    assert len(body['films']) == 3
    titles = [f['title'] for f in body['films']]
    assert set(titles) == {'Action High', 'Action Medium', 'Action Low'}

    # Сортировка по умолчанию (убывание рейтинга)
    assert body['films'][0]['title'] == 'Action High'
    assert body['films'][1]['title'] == 'Action Medium'
    assert body['films'][2]['title'] == 'Action Low'

    # Сортировка по возрастанию
    body, status = await make_get_request('/films-search/api/v1/films/', {'genre': genre_action_id, 'sort': 'imdb_rating'})
    assert body['films'][0]['title'] == 'Action Low'

    # Явная сортировка по убыванию
    body, status = await make_get_request('/films-search/api/v1/films/', {'genre': genre_action_id, 'sort': '-imdb_rating'})
    assert body['films'][0]['title'] == 'Action High'

    # Без фильтра – все 5 фильмов
    body, status = await make_get_request('/films-search/api/v1/films/', {'page_size': 10})
    assert len(body['films']) == 5


async def test_films_list_cache(make_get_request, es_write_data, film_full_data, redis_client: Redis):
    """Кеширование списка фильмов."""
    await es_write_data(film_full_data)
    # Ждём завершения BackgroundTasks от предыдущих тестов, затем сбрасываем кеш
    await asyncio.sleep(0.1)
    await redis_client.flushdb()

    # Первый запрос
    body1, status1 = await make_get_request('/films-search/api/v1/films/', {'page_size': 10})
    assert status1 == 200

    # Второй – из кеша
    body2, status2 = await make_get_request('/films-search/api/v1/films/', {'page_size': 10})
    assert status2 == 200
    assert body1 == body2

    # Другой параметр – другой ключ
    body3, status3 = await make_get_request('/films-search/api/v1/films/', {'page_size': 5})
    assert status3 == 200
    assert body3['page_size'] == 5

    # Сброс кеша
    await redis_client.flushdb()
    body4, status4 = await make_get_request('/films-search/api/v1/films/', {'page_size': 10})
    assert status4 == 200
    assert body4 == body1

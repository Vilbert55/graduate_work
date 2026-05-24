# ruff: noqa: ANN201, ANN001, S101, PLR2004
import asyncio

import pytest
from redis.asyncio import Redis


pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------- Валидация ----------
async def test_search_validation(make_get_request):
    """Граничные случаи валидации параметров."""
    # Отсутствует обязательный query
    _body, status = await make_get_request('/films-search/api/v1/films/search', {})
    assert status == 422

    # Пустая строка query (допустимо)
    _body, status = await make_get_request('/films-search/api/v1/films/search', {'query': ''})
    assert status == 200

    # page_number < 1
    _body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'test', 'page_number': 0})
    assert status == 422

    # page_size < 1
    _body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'test', 'page_size': 0})
    assert status == 422

    # page_size > 100
    _body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'test', 'page_size': 101})
    assert status == 422

    # Граничные значения page_size
    _body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'test', 'page_size': 1})
    assert status == 200
    _body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'test', 'page_size': 100})
    assert status == 200


# ---------- Пагинация ----------
async def test_search_pagination(make_get_request, es_write_data, films_data_for_pagination):
    """Проверка пагинации (вывод N записей, номера страниц)."""
    await es_write_data(films_data_for_pagination)

    # Страница 1, size=10
    body, status = await make_get_request(
        '/films-search/api/v1/films/search',
        {'query': 'Movie', 'page_size': 10, 'page_number': 1},
    )
    assert status == 200
    assert len(body['films']) == 10
    assert body['total'] == 65
    assert body['page'] == 1
    assert body['page_size'] == 10
    assert body['total_pages'] == 7

    # Последняя страница (7)
    body, status = await make_get_request(
        '/films-search/api/v1/films/search',
        {'query': 'Movie', 'page_size': 10, 'page_number': 7},
    )
    assert status == 200
    assert len(body['films']) == 5

    # Страница за пределами
    body, status = await make_get_request(
        '/films-search/api/v1/films/search',
        {'query': 'Movie', 'page_size': 10, 'page_number': 8},
    )
    assert status == 200
    assert len(body['films']) == 0


# ---------- Поиск по фразе ----------
async def test_search_query(make_get_request, es_write_data, films_data_for_search):
    """Проверка поиска записей по текстовой фразе."""
    await es_write_data(films_data_for_search)

    # Запрос "Star Wars" должен найти все фильмы со словом "Star"
    body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'Star Wars'})
    assert status == 200
    assert len(body['films']) == 2  # Star Wars и Star Trek
    # Первый по релевантности должен быть Star Wars
    assert body['films'][0]['title'] == 'Star Wars: A New Hope'

    # Нечёткий поиск (fuzziness)
    body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'Starrr'})
    assert status == 200
    assert len(body['films']) == 2

    # Нет результатов
    body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'Abracadabra'})
    assert status == 200
    assert len(body['films']) == 0

    # Регистронезависимость
    body, status = await make_get_request('/films-search/api/v1/films/search', {'query': 'star wars'})
    assert status == 200
    assert len(body['films']) == 2
    assert body['films'][0]['title'] == 'Star Wars: A New Hope'


# ---------- Кеширование ----------
async def test_search_cache(make_get_request, es_write_data, film_full_data, redis_client: Redis):
    """Проверка работы кеша Redis для поисковых запросов."""
    await redis_client.flushdb()
    await es_write_data(film_full_data)

    # Первый запрос (кеш промах)
    body1, status1 = await make_get_request('/films-search/api/v1/films/search', {'query': 'Detailed', 'page_size': 10})
    assert status1 == 200
    assert body1['films'][0]['title'] == 'Detailed Movie'

    # Второй запрос (кеш попадание)
    body2, status2 = await make_get_request('/films-search/api/v1/films/search', {'query': 'Detailed', 'page_size': 10})
    assert status2 == 200
    assert body1 == body2

    # Другой размер страницы – другой ключ кеша
    body3, status3 = await make_get_request('/films-search/api/v1/films/search', {'query': 'Detailed', 'page_size': 20})
    assert status3 == 200
    assert body3['page_size'] == 20

    # Сброс кеша
    await redis_client.flushdb()
    body4, status4 = await make_get_request('/films-search/api/v1/films/search', {'query': 'Detailed', 'page_size': 10})
    assert status4 == 200
    assert body4 == body1

    # BackgroundTasks записывает ключ после отправки ответа, ждём завершения
    for _ in range(10):
        keys = await redis_client.keys('cache:*')
        if keys:
            break
        await asyncio.sleep(0.05)

    assert len(keys) >= 1

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth.jwt_bearer import TokenData, security_jwt
from src.auth.permissions import require_permission
from src.models.film import (
    FilmDetailResponse,
    FilmShort,
    FilmShortResponse,
    FilmsListResponse,
)
from src.services.film import FilmService, get_film_service


router = APIRouter()


def _calculate_total_pages(total: int, page_size: int) -> int:
    """
    Вычислить общее количество страниц для пагинации.

    Args:
        total: Общее количество элементов
        page_size: Количество элементов на странице

    Returns:
        int: Общее количество страниц (минимум 1)
    """
    return max(1, (total + page_size - 1) // page_size)


def _create_films_list_response(
    films: list[FilmShort],
    total: int,
    page_number: int,
    page_size: int,
) -> FilmsListResponse:
    """
    Создать структурированный ответ со списком фильмов.

    Args:
        films: Список фильмов в кратком формате
        total: Общее количество фильмов
        page_number: Текущий номер страницы
        page_size: Количество элементов на странице

    Returns:
        FilmsListResponse: Структурированный ответ со списком фильмов и метаданными пагинации
    """
    return FilmsListResponse(
        films=[FilmShortResponse.from_film_short(film) for film in films],
        total=total,
        page=page_number,
        page_size=page_size,
        total_pages=_calculate_total_pages(total, page_size),
    )


@router.get("/protected")
async def protected_example(
    token_data: Annotated[TokenData, Depends(security_jwt)],
) -> dict:
    """
    Пример защищённого эндпоинта.
    Возвращает payload из токена.
    """
    return {
        "message": "You have accessed a protected endpoint",
        "user_payload": token_data.payload,
    }


@router.get("/premium")
async def premium_content(
    _: Annotated[dict, Depends(require_permission("premium:access"))],
):
    """Пример эндпоинта требующего проверки прав

    Returns:
        dict:
    """
    return {"data": "Premium content!"}


@router.get("/search")
async def search_films(
    film_service: Annotated[FilmService, Depends(get_film_service)],
    query: Annotated[str, Query(description="Поисковый запрос")],
    page_number: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Размер страницы")] = 50,
) -> FilmsListResponse:
    """
    Поиск фильмов по текстовому запросу.

    Args:
        query: Текст для поиска (ищет в названии, описании, именах актеров и т.д.)
        page_number: Номер страницы (начинается с 1)
        page_size: Количество фильмов на странице (от 1 до 100)

    Returns:
        FilmsListResponse: Список найденных фильмов с пагинацией
    """
    films, total = await film_service.search_films(
        query=query,
        page_number=page_number,
        page_size=page_size,
    )

    return _create_films_list_response(films, total, page_number, page_size)


@router.get("/{film_id}")
async def film_details(
    film_id: UUID,
    film_service: Annotated[FilmService, Depends(get_film_service)],
) -> FilmDetailResponse:
    """
    Получить детальную информацию о конкретном фильме по его ID.

    Args:
        film_id: UUID идентификатор фильма

    Returns:
        FilmDetailResponse: Полная информация о фильме

    Raises:
        HTTPException: 404 если фильм не найден
    """
    film = await film_service.get_by_id(str(film_id))
    if not film:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Film not found",
        )

    return FilmDetailResponse.from_film_detail(film)


@router.get("/")
async def films_list(
    film_service: Annotated[FilmService, Depends(get_film_service)],
    genre: Annotated[UUID | None, Query(description="Фильтр по жанру")] = None,
    sort: Annotated[str, Query(description="Сортировка (например: -imdb_rating, imdb_rating)")] = "-imdb_rating",
    page_number: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Размер страницы")] = 50,
) -> FilmsListResponse:
    """
    Получить список фильмов с возможностью фильтрации и сортировки.

    Args:
        genre: Опциональный фильтр по UUID жанра
        sort: Поле для сортировки (префикс "-" для сортировки по убыванию)
        page_number: Номер страницы (начинается с 1)
        page_size: Количество фильмов на странице (от 1 до 100)

    Returns:
        FilmsListResponse: Список фильмов с пагинацией
    """
    films, total = await film_service.get_films_list(
        genre_id=genre,
        sort=sort,
        page_number=page_number,
        page_size=page_size,
    )

    return _create_films_list_response(films, total, page_number, page_size)


@router.get("/{film_id}/similar")
async def similar_films(
    film_service: Annotated[FilmService, Depends(get_film_service)],
    film_id: UUID,
    page_number: Annotated[int, Query(ge=1, description="Номер страницы")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Размер страницы")] = 50,
) -> FilmsListResponse:
    """
    Получить список фильмов, похожих на указанный фильм (по жанрам).

    Args:
        film_id: UUID фильма, для которого ищем похожие
        page_number: Номер страницы (начинается с 1)
        page_size: Количество фильмов на странице (от 1 до 100)

    Returns:
        FilmsListResponse: Список похожих фильмов с пагинацией
    """
    films, total = await film_service.get_similar_films(
        film_id=film_id,
        page_number=page_number,
        page_size=page_size,
    )

    return _create_films_list_response(films, total, page_number, page_size)

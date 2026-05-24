from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.jwt_bearer import TokenData, security_jwt
from src.schemas.bookmark import BookmarkCreate, BookmarkResponse, BookmarksListResponse
from src.schemas.common import MessageResponse, PaginationParams, make_pagination
from src.services.bookmark import BookmarkService, get_bookmark_service


router = APIRouter()


@router.post('', status_code=status.HTTP_201_CREATED)
async def add_bookmark(
    payload: BookmarkCreate,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[BookmarkService, Depends(get_bookmark_service)],
) -> BookmarkResponse:
    """Добавить фильм в закладки текущего пользователя."""
    bookmark = await service.add(user_id=token_data.user_id, film_id=payload.film_id)
    return BookmarkResponse.model_validate(bookmark)


@router.delete('/{film_id}')
async def remove_bookmark(
    film_id: UUID,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[BookmarkService, Depends(get_bookmark_service)],
) -> MessageResponse:
    """Удалить фильм из закладок текущего пользователя."""
    deleted = await service.remove(user_id=token_data.user_id, film_id=film_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Bookmark not found')
    return MessageResponse(message='Bookmark deleted')


@router.get('')
async def list_bookmarks(
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[BookmarkService, Depends(get_bookmark_service)],
    pagination: Annotated[PaginationParams, Depends()],
) -> BookmarksListResponse:
    """Получить закладки текущего пользователя (сортировка — по времени добавления, новые сверху)."""
    items, total = await service.list_for_user(
        user_id=token_data.user_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return BookmarksListResponse(
        items=[BookmarkResponse.model_validate(item) for item in items],
        pagination=make_pagination(total=total, page=pagination.page, page_size=pagination.page_size),
    )

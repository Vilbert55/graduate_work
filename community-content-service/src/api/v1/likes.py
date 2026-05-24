from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth.jwt_bearer import TokenData, security_jwt
from src.schemas.common import MessageResponse
from src.schemas.like import FilmLikeResponse, FilmLikeStats, FilmLikeUpsert
from src.services.like import FilmLikeService, get_like_service


router = APIRouter()


@router.put('/{film_id}')
async def upsert_like(
    film_id: UUID,
    payload: FilmLikeUpsert,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[FilmLikeService, Depends(get_like_service)],
) -> FilmLikeResponse:
    """Выставить или обновить оценку пользователя для фильма."""
    like = await service.upsert(
        user_id=token_data.user_id,
        film_id=film_id,
        score=payload.score,
    )
    return FilmLikeResponse.model_validate(like)


@router.delete('/{film_id}')
async def delete_like(
    film_id: UUID,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[FilmLikeService, Depends(get_like_service)],
) -> MessageResponse:
    """Удалить оценку пользователя для фильма."""
    deleted = await service.remove(user_id=token_data.user_id, film_id=film_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Like not found')
    return MessageResponse(message='Like deleted')


@router.get('/{film_id}/me')
async def get_my_like(
    film_id: UUID,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[FilmLikeService, Depends(get_like_service)],
) -> FilmLikeResponse:
    """Получить собственную оценку пользователя для фильма."""
    like = await service.get_user_like(user_id=token_data.user_id, film_id=film_id)
    if like is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Like not found')
    return FilmLikeResponse.model_validate(like)


@router.get('/{film_id}/stats')
async def get_film_stats(
    film_id: UUID,
    _: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[FilmLikeService, Depends(get_like_service)],
) -> FilmLikeStats:
    """Получить агрегированную статистику оценок по фильму."""
    return await service.get_stats(film_id)

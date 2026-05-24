from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from src.auth.jwt_bearer import TokenData, security_jwt
from src.schemas.common import MessageResponse, PaginationParams, make_pagination
from src.schemas.review import (
    ReviewCreate,
    ReviewResponse,
    ReviewsListResponse,
    ReviewSortField,
    ReviewUpdate,
    ReviewVoteResponse,
    ReviewVoteUpsert,
)
from src.services.review import ReviewService, get_review_service


router = APIRouter()


def _to_response(review, likes: int, dislikes: int) -> ReviewResponse:
    """Собрать ReviewResponse из модели и агрегатов голосов."""
    return ReviewResponse.model_validate(review).model_copy(update={'likes': likes, 'dislikes': dislikes})


@router.post('', status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: ReviewCreate,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewResponse:
    """Создать рецензию на фильм от имени текущего пользователя."""
    try:
        review = await service.create(
            user_id=token_data.user_id,
            film_id=payload.film_id,
            text=payload.text,
            title=payload.title,
        )
    except IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='User already has a review for this film',
        ) from e
    return _to_response(review, likes=0, dislikes=0)


@router.patch('/{review_id}')
async def update_review(
    review_id: UUID,
    payload: ReviewUpdate,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewResponse:
    """Обновить собственную рецензию."""
    review = await service.update(
        review_id=review_id,
        user_id=token_data.user_id,
        text=payload.text,
        title=payload.title,
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Review not found')

    data = await service.get(review_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Review not found')
    review, likes, dislikes = data
    return _to_response(review, likes=likes, dislikes=dislikes)


@router.delete('/{review_id}')
async def delete_review(
    review_id: UUID,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> MessageResponse:
    """Удалить собственную рецензию."""
    deleted = await service.delete(review_id=review_id, user_id=token_data.user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Review not found')
    return MessageResponse(message='Review deleted')


@router.get('/{review_id}')
async def get_review(
    review_id: UUID,
    _: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewResponse:
    """Получить рецензию по её ID."""
    data = await service.get(review_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Review not found')
    review, likes, dislikes = data
    return _to_response(review, likes=likes, dislikes=dislikes)


@router.get('')
async def list_reviews(
    _: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    pagination: Annotated[PaginationParams, Depends()],
    film_id: Annotated[UUID, Query(description='ID фильма')],
    sort: Annotated[ReviewSortField, Query(description='Поле сортировки')] = ReviewSortField.CREATED_AT,
    order: Annotated[str, Query(pattern='^(asc|desc)$', description='Направление сортировки')] = 'desc',
) -> ReviewsListResponse:
    """Получить список рецензий к фильму с гибкой сортировкой."""
    items, total = await service.list_for_film(
        film_id=film_id,
        sort=sort,
        order_desc=order == 'desc',
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return ReviewsListResponse(
        items=[_to_response(r, likes=likes_n, dislikes=dislikes_n) for r, likes_n, dislikes_n in items],
        pagination=make_pagination(total=total, page=pagination.page, page_size=pagination.page_size),
    )


@router.put('/{review_id}/vote')
async def upsert_vote(
    review_id: UUID,
    payload: ReviewVoteUpsert,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewVoteResponse:
    """Проголосовать за рецензию (лайк/дизлайк) или обновить голос."""
    vote = await service.upsert_vote(
        review_id=review_id,
        user_id=token_data.user_id,
        score=payload.score,
    )
    if vote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Review not found')
    return ReviewVoteResponse.model_validate(vote)


@router.delete('/{review_id}/vote')
async def delete_vote(
    review_id: UUID,
    token_data: Annotated[TokenData, Depends(security_jwt)],
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> MessageResponse:
    """Отозвать голос за рецензию."""
    deleted = await service.delete_vote(review_id=review_id, user_id=token_data.user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Vote not found')
    return MessageResponse(message='Vote deleted')

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.postgres import get_session
from src.db.redis import get_redis
from src.models.entity import User
from src.schemas.role import RoleCreate, RoleResponse, RoleUpdate
from src.services.role import RoleService
from src.utils.dependencies import get_current_superuser


router = APIRouter(prefix="/auth/roles", tags=["roles"])


@router.get(
    "",
    response_model=list[RoleResponse],
    summary="Список всех ролей",
    description="Возвращает все существующие роли. Доступно только суперпользователю.",
    responses={
        200: {"description": "Список ролей"},
        401: {"description": "Неавторизован"},
        403: {"description": "Доступ запрещён (не суперпользователь)"},
    },
)
async def get_roles(
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[User, Depends(get_current_superuser)],
):
    """Получить список всех ролей. Только для суперпользователя."""
    return await RoleService(db, redis).get_all_roles()


@router.post(
    "",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать новую роль",
    responses={
        201: {"description": "Роль создана"},
        400: {"description": "Ошибка валидации (например, имя уже существует)"},
        401: {"description": "Неавторизован"},
        403: {"description": "Доступ только для суперпользователя"},
        409: {"description": "Роль с таким именем уже существует"},
    },
)
async def create_role(
    role_data: RoleCreate,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[User, Depends(get_current_superuser)],
):
    """
    Создаёт новую роль.

    **Доступно только суперпользователю.**

    - **name**: уникальное название роли (макс. 50 символов)
    - **description**: описание роли (опционально)

    При успехе возвращает созданную роль.
    """
    return await RoleService(db, redis).create_role(role_data)


@router.put(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Обновить роль",
    description="Обновляет название и/или описание существующей роли. Доступно только суперпользователю.",
    responses={
        200: {"description": "Роль обновлена"},
        400: {"description": "Ошибка валидации (например, имя уже занято)"},
        401: {"description": "Неавторизован"},
        403: {"description": "Доступ запрещён (не суперпользователь)"},
        404: {"description": "Роль не найдена"},
        409: {"description": "Роль с таким именем уже существует"},
    },
)
async def update_role(
    role_id: UUID,
    role_data: RoleUpdate,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[User, Depends(get_current_superuser)],
):
    """Обновить роль. Только для суперпользователя."""
    return await RoleService(db, redis).update_role(role_id, role_data)


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить роль",
    description="Удаляет роль и все связи с пользователями. Доступно только суперпользователю.",
    responses={
        204: {"description": "Роль удалена"},
        401: {"description": "Неавторизован"},
        403: {"description": "Доступ запрещён"},
        404: {"description": "Роль не найдена"},
    },
)
async def delete_role(
    role_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[User, Depends(get_current_superuser)],
):
    """Удалить роль. Только для суперпользователя."""
    await RoleService(db, redis).delete_role(role_id)

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PermissionDeniedError
from src.db.postgres import get_session
from src.db.redis import get_redis
from src.models.entity import User
from src.schemas.user import UserResponse
from src.services.role import RoleService
from src.services.user import UserService
from src.utils.dependencies import get_current_superuser, get_current_user


router = APIRouter(prefix="/auth/users", tags=["users"])


@router.post(
    "/{user_id}/roles/{role_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Назначить роль пользователю",
    description="Добавляет роль указанному пользователю. Только для суперпользователя.",
    responses={
        201: {"description": "Роль назначена"},
        401: {"description": "Неавторизован"},
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь или роль не найдены"},
        409: {"description": "Роль уже назначена"},
    },
)
async def assign_role(
    user_id: UUID,
    role_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[User, Depends(get_current_superuser)],
):
    """Назначить роль пользователю. Только для суперпользователя."""
    await RoleService(db, redis).assign_role(user_id, role_id)
    return {"message": "Role assigned"}


@router.delete(
    "/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать роль у пользователя",
    description="Удаляет назначение роли у указанного пользователя. Доступно только суперпользователю.",
    responses={
        204: {"description": "Роль отозвана"},
        401: {"description": "Неавторизован"},
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь или роль не найдены"},
        409: {"description": "У пользователя нет такой роли"},
    },
)
async def remove_role(
    user_id: UUID,
    role_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[User, Depends(get_current_superuser)],
):
    """Отозвать роль у пользователя. Только для суперпользователя."""
    await RoleService(db, redis).remove_role(user_id, role_id)


@router.get(
    "/{user_id}/permissions",
    response_model=dict,
    summary="Проверка прав доступа",
    description="Проверяет, имеет ли пользователь доступ к указанному ресурсу.",
    responses={
        403: {"description": "Not enough permissions to check other users"},
        404: {"description": "User not found"},
    },
)
async def check_permissions(
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_user)],
    user_id: UUID,
    resource: Annotated[str, Query(description="Ресурс для проверки прав (например, 'movies:view')")],
):
    """
    Проверить, имеет ли пользователь права на ресурс.
    Доступно только суперпользователю или самому пользователю (для своих прав).

    Returns:
        dict: {"user_id": str, "resource": str, "has_permission": bool}
    """
    # Разрешаем только суперпользователю или если запрашивает свои права
    if not current_user.is_superuser and str(current_user.id) != str(user_id):
        raise PermissionDeniedError("Not enough permissions to check other users' permissions")

    # Здесь должна быть логика проверки прав на ресурс.
    # Для демо используем простую эвристику:
    # - Суперпользователь всегда имеет доступ.
    # - Иначе проверяем наличие роли, совпадающей с ресурсом (например, роль "movie_viewer" для ресурса "movies:view").
    target_user = await UserService(db, redis).get_user_or_404(user_id)
    if target_user.is_superuser:
        has_permission = True
    else:
        role_service = RoleService(db, redis)
        user_roles = await role_service.get_user_roles(user_id)
        role_names = [role.name for role in user_roles]
        # Упрощённо: если у пользователя есть роль "admin", даём доступ ко всему
        if "admin" in role_names:  # noqa: SIM108
            has_permission = True
        else:
            # Можно реализовать маппинг resource -> требуемая роль
            # Например, для ресурса "movies:view" нужна роль "movie_viewer"
            # Пока заглушка
            has_permission = False

    return {"user_id": str(user_id), "resource": resource, "has_permission": has_permission}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Профиль текущего пользователя",
    description="Возвращает информацию о текущем авторизованном пользователе, включая список его ролей.",
    responses={
        200: {"description": "Информация о пользователе"},
        401: {"description": "Неавторизован"},
    },
)
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    """Получить профиль текущего пользователя.
    Доступно любому авторизованному пользователю.
    """
    roles = await RoleService(db, redis).get_user_roles(current_user.id)
    user_data = UserResponse.model_validate(current_user)
    user_data.roles = roles
    return user_data


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_profile(
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Получить профиль пользователя.
    Доступно суперпользователю или самому пользователю.
    """
    if not current_user.is_superuser and str(current_user.id) != str(user_id):
        raise PermissionDeniedError("Not enough permissions")

    user = await UserService(db, redis).get_user_or_404(user_id)
    roles = await RoleService(db, redis).get_user_roles(user_id)

    user_data = UserResponse.model_validate(user)
    user_data.roles = roles
    return user_data

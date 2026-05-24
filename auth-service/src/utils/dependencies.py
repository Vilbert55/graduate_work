import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PermissionDeniedError, UnauthorizedError
from src.core.security import decode_token
from src.db.postgres import get_session
from src.db.redis import get_redis, redis_key_user, redis_key_user_permissions
from src.models.entity import User
from src.services.role import RoleService
from src.services.user import UserService


logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> User:
    token = credentials.credentials
    try:
        payload = await decode_token(token)
    except ValueError:
        raise UnauthorizedError("Invalid authentication token") from None

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    cache_key = redis_key_user(user_id)
    cached = await redis.get(cache_key)
    if cached:
        user_data = json.loads(cached)
        if user_data.get("created_at"):
            user_data["created_at"] = datetime.fromisoformat(user_data["created_at"])

        return User(**user_data)

    user = await UserService(db, redis).get_user_or_404(user_id)

    user_dict = {
        "id": str(user.id),
        "login": user.login,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "is_superuser": user.is_superuser,
    }
    await redis.setex(cache_key, 900, json.dumps(user_dict))

    return user


async def get_current_superuser(  # noqa: RUF029
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_superuser:
        raise PermissionDeniedError("Not enough permissions")
    return current_user


def get_user_with_permission(permission_name: str) -> Callable:
    async def _check_permission(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_session)],
        redis: Annotated[Redis, Depends(get_redis)],
    ) -> User:
        if current_user.is_superuser:
            return current_user

        cache_key = redis_key_user_permissions(current_user.id)
        cached = await redis.get(cache_key)
        if cached:
            perms = json.loads(cached)
            if permission_name in perms:
                return current_user
            raise PermissionDeniedError("Permission denied")

        roles = await RoleService(db, redis).get_user_roles(current_user.id)
        role_names = [role.name for role in roles]

        await redis.setex(cache_key, 300, json.dumps(role_names))

        if permission_name in role_names:
            return current_user
        raise PermissionDeniedError("Permission denied")

    return _check_permission

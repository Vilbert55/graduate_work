import logging
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status

from src.auth.jwt_bearer import TokenData, security_jwt
from src.core.config import settings


logger = logging.getLogger(__name__)


def require_permission(resource: str):
    """
    Фабрика зависимостей, проверяющая наличие права на ресурс через auth-сервис.
    При любой ошибке проверки (сеть, недоступность, отказ) возвращает 403 Forbidden.
    """
    async def _checker(
        token_data: Annotated[TokenData, Depends(security_jwt)],
    ) -> None:
        user_id = token_data.payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        url = f"http://{settings.auth_host}:{settings.auth_port}/auth/users/{user_id}/permissions"
        params = {"resource": resource}
        headers = {"Authorization": f"Bearer {token_data.token}"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, headers=headers, timeout=2.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            # Любая ошибка при запросе к auth-сервису -> логируем и возвращаем 403
            logger.exception(f"Permission check failed for user {user_id}, resource '{resource}'")
        else:
            if data.get("has_permission"):
                return
            # Право отсутствует:
            logger.info(f"User {user_id} does not have permission '{resource}'")

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    return _checker

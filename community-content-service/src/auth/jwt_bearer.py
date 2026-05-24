import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt

from src.core.config import settings


logger = logging.getLogger(__name__)


def decode_token(token: str) -> dict | None:
    """Декодировать JWT и вернуть payload, либо None при ошибке."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={'require': ['exp', 'sub']},
        )
    except jwt.JWTError as e:
        logger.warning(f"JWT decode error: {e}")
    return None


@dataclass
class TokenData:
    """Полезная нагрузка JWT и сам исходный токен."""

    payload: dict
    token: str

    @property
    def user_id(self) -> UUID:
        """Извлечь идентификатор пользователя из токена."""
        sub = self.payload.get('sub')
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid token payload',
            )
        try:
            return UUID(str(sub))
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid user id in token: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid token payload',
            ) from e


class JWTBearer(HTTPBearer):
    """Проверка JWT в заголовке Authorization."""

    def __init__(self, auto_error: bool = True) -> None:  # noqa: FBT001, FBT002
        super().__init__(auto_error=auto_error)

    async def __call__(self, request: Request) -> TokenData:
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Invalid authorization code.',
            )
        if credentials.scheme.lower() != 'bearer':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Only Bearer token might be accepted',
                headers={'WWW-Authenticate': 'Bearer'},
            )
        token = credentials.credentials
        payload = decode_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Invalid or expired token.',
            )
        return TokenData(payload=payload, token=token)


# Экземпляр зависимости для эндпоинтов
security_jwt = JWTBearer()

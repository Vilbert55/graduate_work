import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt

from src.core.config import settings


logger = logging.getLogger(__name__)


def decode_token(token: str) -> dict | None:
    """
    Декодирует JWT-токен, используя секретный ключ из настроек.
    Возвращает payload или None в случае ошибки.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.JWTError as e:
        logger.warning(f"JWT decode error: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error decoding token: {e}")  # noqa: TRY401
    return None


@dataclass
class TokenData:
    """Содержит полезную нагрузку из токена и сам сырой токен."""
    payload: dict
    token: str


class JWTBearer(HTTPBearer):
    """
    Класс для проверки JWT-токена в заголовке Authorization.
    Возвращает TokenData (payload и сырой токен), если токен валиден.
    """

    def __init__(self, auto_error: bool = True) -> None:  # noqa: FBT001, FBT002
        super().__init__(auto_error=auto_error)

    async def __call__(self, request: Request) -> TokenData:
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authorization code.",
            )
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Only Bearer token might be accepted",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials
        payload = self.parse_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or expired token.",
            )
        return TokenData(payload=payload, token=token)

    @staticmethod
    def parse_token(jwt_token: str) -> dict | None:
        return decode_token(jwt_token)


# Экземпляр зависимости, который будем использовать в эндпоинтах
security_jwt = JWTBearer()

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from async_fastapi_jwt_auth import AuthJWT
from async_fastapi_jwt_auth.exceptions import AuthJWTException, JWTDecodeError
from passlib.context import CryptContext

from src.core.config import settings


# Контекст для хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Пул потоков для CPU-bound операций
_thread_pool = ThreadPoolExecutor(max_workers=4)


@AuthJWT.load_config
def get_config():
    """
    Возвращает конфигурацию для AuthJWT в виде списка кортежей.
    """
    return [
        ("authjwt_secret_key", settings.jwt_secret_key),
        ("authjwt_algorithm", settings.jwt_algorithm),
        ("authjwt_access_token_expires", timedelta(minutes=settings.access_token_expire_minutes)),
        ("authjwt_refresh_token_expires", timedelta(days=settings.refresh_token_expire_days)),
    ]


async def create_access_token(subject: str) -> str:
    """Создаёт access token."""
    auth = AuthJWT()
    return await auth.create_access_token(subject=subject)


async def create_refresh_token(subject: str) -> str:
    """Создаёт refresh token."""
    auth = AuthJWT()
    return await auth.create_refresh_token(subject=subject)


async def decode_token(token: str) -> dict[str, Any]:
    """Декодирует токен и возвращает его payload."""
    auth = AuthJWT()
    try:
        return await auth.get_raw_jwt(encoded_token=token)
    except (AuthJWTException, JWTDecodeError) as e:
        raise ValueError(f"Invalid token: {e}") from None


def compute_token_hash(token: str) -> str:
    """Возвращает SHA-256 хеш токена."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Синхронная проверка пароля (блокирующая)."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Синхронное хеширование пароля (блокирующее)."""
    return pwd_context.hash(password)


async def async_verify_password(plain_password: str, hashed_password: str) -> bool:
    """Асинхронная обёртка проверки пароля в thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _thread_pool, verify_password, plain_password, hashed_password,
    )


async def async_get_password_hash(password: str) -> str:
    """Асинхронная обёртка хеширования пароля в thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thread_pool, get_password_hash, password)

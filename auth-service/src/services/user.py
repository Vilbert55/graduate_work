import logging
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    CredentialsError,
    LoginAlreadyTakenError,
    UserNotFoundError,
)
from src.core.security import async_get_password_hash, async_verify_password
from src.db.redis import redis_key_user
from src.models.entity import User


logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def _get_user_by_id(self, user_id: UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def _get_by_login(self, login: str) -> User | None:
        result = await self.db.execute(select(User).where(User.login == login))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def update_login(self, user_id: UUID, new_login: str, password: str) -> User:
        user = await self.get_user_or_404(user_id)

        if not await async_verify_password(password, user.password):
            raise CredentialsError("Invalid password")

        # Проверить уникальность нового логина
        existing = await self._get_by_login(new_login)
        if existing and existing.id != user_id:
            raise LoginAlreadyTakenError("Login already taken")

        user.login = new_login
        await self.db.commit()
        await self.db.refresh(user)

        await self.redis.delete(redis_key_user(user_id))
        logger.info("User %s changed login to %s", user_id, new_login)
        return user

    async def get_user_or_404(self, user_id: UUID) -> User:
        if user := await self._get_user_by_id(user_id):
            return user
        raise UserNotFoundError(f"User '{user_id}' not found")

    async def update_password(self, user_id: UUID, new_password: str) -> None:
        user = await self.get_user_or_404(user_id)

        user.password = await async_get_password_hash(new_password)
        await self.db.commit()
        await self.redis.delete(redis_key_user(user_id))
        logger.info("User %s changed password", user_id)

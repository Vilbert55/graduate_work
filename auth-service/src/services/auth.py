import logging
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import (
    CredentialsError,
    UnauthorizedError,
    UserAlreadyExistsError,
)
from src.core.security import (
    async_get_password_hash,
    async_verify_password,
    compute_token_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from src.models.entity import LoginHistory, RefreshToken, User
from src.schemas.auth import UserCreate


logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def register(self, user_data: UserCreate) -> User:
        """Регистрация нового пользователя."""
        existing = await self.db.execute(
            select(User).where(User.login == user_data.login),
        )
        if existing.scalar_one_or_none():
            raise UserAlreadyExistsError("Login already exists")

        hashed_password = await async_get_password_hash(user_data.password)

        user = User(
            login=user_data.login,
            password=hashed_password,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            gender=user_data.gender,
            age_group=user_data.age_group,
            country=user_data.country,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        logger.info(f"New user registered: {user.login}")
        return user

    async def authenticate(self, login: str, password: str) -> User:
        """Аутентификация пользователя. В случае неудачи кидает CredentialsError."""
        result = await self.db.execute(select(User).where(User.login == login))
        user = result.scalar_one_or_none()
        if not user or not await async_verify_password(password, user.password):
            raise CredentialsError("Incorrect login or password")
        return user

    async def login(
        self, user: User, user_agent: str, ip_address: str,
    ) -> tuple[str, str]:
        access_token = await create_access_token(subject=str(user.id))
        refresh_token = await create_refresh_token(subject=str(user.id))

        token_hash = compute_token_hash(refresh_token)
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=settings.refresh_token_expire_days)

        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            device_info=user_agent,
            expires_at=expires_at,
        )
        self.db.add(refresh_record)

        history_entry = LoginHistory(
            user_id=user.id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.db.add(history_entry)

        await self.db.commit()
        logger.info(f"User {user.login} logged in from {ip_address}")
        return access_token, refresh_token

    async def refresh(self, refresh_token: str, user_agent: str, _ip_address: str) -> str:
        try:
            payload = await decode_token(refresh_token)
        except ValueError:
            raise UnauthorizedError("Invalid refresh token") from None

        user_id = payload.get("sub")
        if not user_id:
            raise UnauthorizedError("Invalid token payload")

        token_hash = compute_token_hash(refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.user_id == user_id,
                RefreshToken.expires_at > datetime.now(UTC).replace(tzinfo=None),
            ),
        )
        db_token = result.scalar_one_or_none()
        if not db_token:
            raise UnauthorizedError("Refresh token not found or expired")

        if db_token.device_info != user_agent:
            db_token.device_info = user_agent
            await self.db.commit()

        new_access = await create_access_token(subject=user_id)
        logger.info("Access token refreshed for user %s", user_id)
        return new_access

    async def logout(self, refresh_token: str, user_id: str) -> None:
        token_hash = compute_token_hash(refresh_token)
        result = await self.db.execute(
            delete(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.user_id == user_id,
            ),
        )
        await self.db.commit()
        if result.rowcount == 0:
            # Токен не найден или не принадлежит пользователю
            raise UnauthorizedError("Refresh token not found or invalid")
        logger.info("User %s logged out (device)", user_id)

    async def logout_all(self, user_id: str) -> None:
        await self.db.execute(
            delete(RefreshToken).where(RefreshToken.user_id == user_id),
        )
        await self.db.commit()
        logger.info("User %s logged out from all devices", user_id)

    async def get_login_history(self, user_id: str, limit: int = 20, offset: int = 0) -> list[LoginHistory]:
        result = await self.db.execute(
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.created_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return result.scalars().all()

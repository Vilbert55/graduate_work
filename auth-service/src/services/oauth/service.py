import logging
import random
import uuid
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, OAuthLinkRequiredError
from src.core.security import async_get_password_hash
from src.models.entity import User, UserOAuthProvider


logger = logging.getLogger(__name__)


class OAuthService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    async def _generate_unique_login(self, base_login: str) -> str:
        """Генерирует уникальный логин на основе базового."""
        login = base_login
        for _ in range(10):
            result = await self.db.execute(select(User).where(User.login == login))
            if not result.scalar_one_or_none():
                return login
            login = f"{base_login}{random.randint(1, 999)}"
        raise ConflictError("Could not generate unique login")

    async def process_provider_login(self, provider_name: str, user_info: dict) -> User:  # noqa: PLR0914
        """
        Обрабатывает данные от провайдера.
        Возвращает объект User, если пользователь может войти.
        В противном случае выбрасывает OAuthLinkRequiredError.
        """
        provider_user_id = user_info["provider_user_id"]
        email = user_info["email"]
        login_hint = user_info.get("login")
        first_name = user_info.get("first_name")
        last_name = user_info.get("last_name")

        # Проверяем, есть ли уже привязка этого провайдера
        stmt = select(UserOAuthProvider).where(
            UserOAuthProvider.provider == provider_name,
            UserOAuthProvider.provider_user_id == provider_user_id,
        )
        result = await self.db.execute(stmt)
        provider_link = result.scalar_one_or_none()

        if provider_link:
            # Провайдер привязан – возвращаем пользователя
            user_stmt = select(User).where(User.id == provider_link.user_id)
            user_result = await self.db.execute(user_stmt)
            return user_result.scalar_one()

        # Ищем пользователя по email
        user_stmt = select(User).where(User.email == email)
        user_result = await self.db.execute(user_stmt)
        existing_user = user_result.scalar_one_or_none()

        if existing_user:
            raise OAuthLinkRequiredError(
                msg="User with this email already exists. Please link your account.",
                details={
                    "user_id": str(existing_user.id),
                    "provider": provider_name,
                    "provider_user_id": provider_user_id,
                    "email": email,
                },
            )

        # Создаём нового пользователя
        unique_login = await self._generate_unique_login(login_hint)

        # Случайный пароль (пользователь не будет входить по паролю)
        temp_password = str(uuid.uuid4())
        hashed_password = await async_get_password_hash(temp_password)

        user = User(
            login=unique_login,
            email=email,
            password=hashed_password,
            first_name=first_name,
            last_name=last_name,
        )
        self.db.add(user)
        await self.db.flush()   # получаем id

        link = UserOAuthProvider(
            user_id=user.id,
            provider=provider_name,
            provider_user_id=provider_user_id,
            provider_email=email,
        )
        self.db.add(link)
        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"New user registered via {provider_name}: {user.login}")
        return user

    async def create_provider_link(
        self, user_id: UUID, provider: str,
        provider_user_id: str, provider_email: str | None = None,
    ) -> None:
        """Привязывает аккаунт соцсети к существующему пользователю."""
        # Проверим, нет ли уже такой привязки у другого пользователя
        stmt = select(UserOAuthProvider).where(
            UserOAuthProvider.provider == provider,
            UserOAuthProvider.provider_user_id == provider_user_id,
        )
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            raise ConflictError("Provider already linked to another user")

        link = UserOAuthProvider(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )
        self.db.add(link)
        await self.db.commit()
        logger.info("Provider %s linked to user %s", provider, user_id)

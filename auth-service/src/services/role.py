import logging
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, RoleNotFoundError
from src.db.redis import redis_key_user_permissions
from src.models.entity import Role, UserRole
from src.schemas.role import RoleCreate, RoleUpdate
from src.services.user import UserService


logger = logging.getLogger(__name__)


class RoleService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def create_role(self, role_data: RoleCreate) -> Role:
        role = Role(name=role_data.name, description=role_data.description)
        self.db.add(role)
        try:
            await self.db.commit()
            await self.db.refresh(role)
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(f"Role with name '{role_data.name}' already exists") from None
        logger.info(f"Role created: {role.name}")
        return role

    async def _get_role(self, role_id: UUID) -> Role | None:
        result = await self.db.execute(select(Role).where(Role.id == role_id))
        return result.scalar_one_or_none()

    async def get_all_roles(self) -> list[Role]:
        result = await self.db.execute(select(Role).order_by(Role.name))
        return result.scalars().all()

    async def update_role(self, role_id: UUID, role_data: RoleUpdate) -> Role:
        role = await self._get_role(role_id)
        if not role:
            raise RoleNotFoundError("Role not found")

        if role_data.name is not None and role_data.name != role.name:
            role.name = role_data.name
        if role_data.description is not None:
            role.description = role_data.description

        try:
            await self.db.commit()
            await self.db.refresh(role)
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(f"Role with name '{role_data.name}' already exists") from None

        logger.info(f"Role updated: {role.name}")
        return role

    async def delete_role(self, role_id: UUID) -> None:
        role = await self._get_role(role_id)
        if not role:
            raise RoleNotFoundError("Role not found")

        # Удалить связи с пользователями
        await self.db.execute(delete(UserRole).where(UserRole.role_id == role_id))
        await self.db.delete(role)
        await self.db.commit()
        logger.info(f"Role deleted: {role.name}")

    async def assign_role(self, user_id: UUID, role_id: UUID) -> UserRole:
        # Проверить существование пользователя и роли
        await UserService(self.db, self.redis).get_user_or_404(user_id)
        role = await self._get_role(role_id)
        if not role:
            raise RoleNotFoundError("Role not found")

        user_role = UserRole(user_id=user_id, role_id=role_id)
        self.db.add(user_role)
        try:
            await self.db.commit()
            await self.db.refresh(user_role)
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError("User already has this role") from None

        await self.redis.delete(redis_key_user_permissions(user_id))
        logger.info(f"Role {role.name} assigned to user {user_id}")
        return user_role

    async def remove_role(self, user_id: UUID, role_id: UUID) -> None:
        # Проверить существование пользователя
        await UserService(self.db, self.redis).get_user_or_404(user_id)

        result = await self.db.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            ),
        )
        if result.rowcount == 0:
            raise ConflictError("User does not have this role")
        await self.db.commit()
        await self.redis.delete(redis_key_user_permissions(user_id))
        logger.info("Role %s removed from user %s", role_id, user_id)

    async def get_user_roles(self, user_id: UUID) -> list[Role]:
        result = await self.db.execute(
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.name),
        )
        return result.scalars().all()

    async def user_has_role(self, user_id: UUID, role_name: str) -> bool:
        result = await self.db.execute(
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.name == role_name),
        )
        return result.scalar_one_or_none() is not None

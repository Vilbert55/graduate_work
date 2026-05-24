"""Клиент к auth-сервису.

В учебном проекте у нас единая БД — читаем `auth.users` напрямую.
Интерфейс изолирован, поэтому при необходимости можно заменить
реализацию на HTTPAuthClient без правок вызывающего кода.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, text


if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UserData:
    id: UUID
    login: str
    email: str | None
    first_name: str | None
    last_name: str | None


class AuthClient:
    """DB-based реализация клиента к auth-сервису.

    Все методы async и работают с переданным AsyncSession,
    чтобы можно было встраиваться в чужие транзакции (для атомарности).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user(self, user_id: UUID) -> UserData | None:
        """Возвращает данные пользователя по id или None, если не найден."""
        row = (await self._session.execute(
            text("""
                SELECT id, login, email, first_name, last_name
                FROM auth.users
                WHERE id = :user_id
            """),
            {"user_id": str(user_id)},
        )).first()
        if row is None:
            return None
        return UserData(
            id=row.id,
            login=row.login,
            email=row.email,
            first_name=row.first_name,
            last_name=row.last_name,
        )

    async def get_users(self, user_ids: Iterable[UUID]) -> dict[UUID, UserData]:
        """Возвращает словарь {user_id: UserData} для переданных id."""
        ids = [str(u) for u in user_ids]
        if not ids:
            return {}
        # bindparam expanding=True раскрывает список в (:1, :2, ...) — работает в asyncpg.
        stmt = text("""
            SELECT id, login, email, first_name, last_name
            FROM auth.users
            WHERE id IN :user_ids
        """).bindparams(bindparam("user_ids", expanding=True))
        rows = (await self._session.execute(stmt, {"user_ids": ids})).all()
        return {
            row.id: UserData(
                id=row.id,
                login=row.login,
                email=row.email,
                first_name=row.first_name,
                last_name=row.last_name,
            )
            for row in rows
        }

    async def get_all_user_ids(self) -> list[UUID]:
        """Возвращает список id всех пользователей из auth.users."""
        rows = (await self._session.execute(
            text("SELECT id FROM auth.users ORDER BY created_at"),
        )).all()
        return [row.id for row in rows]

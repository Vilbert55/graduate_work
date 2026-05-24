import asyncio

import typer
from sqlalchemy import select
from src.core.security import get_password_hash
from src.db.postgres import async_session
from src.models.entity import User


app = typer.Typer()


@app.command()
def create_superuser(login: str, password: str):
    """Создаёт суперпользователя, если его ещё нет."""

    async def _create() -> None:
        async with async_session() as session:
            result = await session.execute(select(User).where(User.login == login))
            if result.scalar_one_or_none():
                print(f"User {login} already exists.")
                return
            new_user = User(
                login=login,
                password=get_password_hash(password),
                is_superuser=True,
            )
            session.add(new_user)
            await session.commit()
            print(f"Superuser {login} created.")

    asyncio.run(_create())


@app.command()
def list_users():
    """Выводит список всех пользователей (для отладки)."""

    async def _list() -> None:
        async with async_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
            for user in users:
                print(f"{user.login} (superuser: {user.is_superuser})")

    asyncio.run(_list())


if __name__ == "__main__":
    app()

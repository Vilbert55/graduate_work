"""seed-users — создать N тестовых юзеров в auth.users (идемпотентно).

Идемпотентность: маркер `auth.users.is_demo = TRUE`. Повторный запуск
сначала удаляет всех с этим флагом, потом создаёт count новых. На
реальных пользователей команда не влияет.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from itertools import product

import asyncpg
import typer
from bcrypt import gensalt, hashpw
from faker import Faker

from src.config import settings
from src.segments import AGE_BANDS, band_range


# Все демо-юзеры создаются с одним фиксированным паролем: это тестовые
# аккаунты, единый пароль упрощает демо.
DEMO_PASSWORD = "demo_password"  # noqa: S105

# Сегменты для распределения
DEFAULT_SEGMENTS = list(product(
    ["female", "male"],
    list(AGE_BANDS),
    ["RU"],
))


def _make_login(idx: int, segment: tuple[str, str, str]) -> str:
    """Логин вида demo_female_25-34_RU_0007 (в логине — полоса, не точный возраст)."""
    g, a, c = segment
    return f"demo_{g}_{a}_{c}_{idx:04d}"


def _hash_password(password: str) -> str:
    """bcrypt-хеш, совместимый с passlib.CryptContext(['bcrypt']) в auth-service."""
    return hashpw(password.encode("utf-8"), gensalt()).decode("utf-8")


async def _seed(count: int, segment_filter: str | None) -> int:
    if count <= 0:
        return 0

    if segment_filter:
        try:
            g, a, c = segment_filter.split("_")
            segments = [(g, a, c)]
        except ValueError:
            raise typer.BadParameter(
                "--segment expected 'gender_age_country', e.g. 'female_25-34_RU'",
            ) from None
        if a not in AGE_BANDS:
            raise typer.BadParameter(
                f"--segment age band must be one of: {', '.join(AGE_BANDS)}",
            )
    else:
        segments = DEFAULT_SEGMENTS

    faker = Faker()
    pwd_hash = _hash_password(DEMO_PASSWORD)

    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        # Идемпотентность: сначала удаляем зависимые от users строки (внешние
        # ключи), затем самих демо-юзеров.
        await conn.execute("DELETE FROM auth.refresh_tokens WHERE user_id IN (SELECT id FROM auth.users WHERE is_demo)")
        await conn.execute("DELETE FROM auth.user_roles    WHERE user_id IN (SELECT id FROM auth.users WHERE is_demo)")
        await conn.execute(
            "DELETE FROM auth.user_oauth_providers WHERE user_id IN (SELECT id FROM auth.users WHERE is_demo)",
        )
        await conn.execute("DELETE FROM auth.users WHERE is_demo")

        rows = []
        for i in range(count):
            segment = random.choice(segments)
            login = _make_login(i, segment)
            lo, hi = band_range(segment[1])
            rows.append((
                uuid.uuid4(),
                login,
                f"{login}@demo.local",  # email-канал требует адрес; Mailpit примет любой
                pwd_hash,
                faker.first_name_female() if segment[0] == "female" else faker.first_name_male(),
                faker.last_name(),
                segment[0],
                random.randint(lo, hi),  # конкретный возраст внутри полосы сегмента
                segment[2],
            ))

        await conn.executemany(
            """
            INSERT INTO auth.users(
                id, login, email, password, first_name, last_name,
                gender, age, country, is_demo, created_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, TRUE, (now() AT TIME ZONE 'utc')
            )
            """,
            rows,
        )
    finally:
        await conn.close()

    return len(rows)


def seed_users_cmd(
    count: int = typer.Option(50, "--count", "-n", help="Сколько юзеров создать."),
    segment: str | None = typer.Option(
        None, "--segment", "-s",
        help="Ограничить одним сегментом 'gender_age_country', напр. female_25-34_RU.",
    ),
) -> None:
    """Создать count демо-юзеров (идемпотентно: предыдущих с is_demo=TRUE удалит).

    Пароль у всех демо-юзеров фиксированный — DEMO_PASSWORD ('demo_password').
    """
    created = asyncio.run(_seed(count, segment))
    typer.echo(f"OK: deleted previous is_demo users, created {created} new demo users")

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.db.postgres import get_session
from src.db.redis import get_redis
from src.models.entity import User
from src.schemas.auth import (
    LoginChange,
    LoginHistoryResponse,
    PasswordChange,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
)
from src.services.auth import AuthService
from src.services.user import UserService
from src.utils.dependencies import get_current_user
from src.utils.rate_limit import rate_limit


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Регистрация нового пользователя",
    description="Создаёт пользователя и сразу выполняет вход. Возвращает access и refresh токены.",
    responses={
        201: {"description": "Пользователь успешно создан, возвращены токены"},
        400: {"description": "Ошибка валидации (например, логин уже занят)"},
        409: {"description": "Пользователь с таким логином уже существует"},
    },
)
async def register(
    user_data: UserCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[None, Depends(
        rate_limit(
            requests=settings.register_rate_limit_requests,  # макс. попыток регистраций за время period
            period=settings.register_rate_limit_period,
        ),
    )],
):
    """
    Создаёт нового пользователя и сразу выполняет вход.

    - **login**: уникальное имя пользователя
    - **password**: пароль (минимум 6 символов)
    - **first_name**, **last_name**: опционально

    При успехе возвращает **access_token** и **refresh_token**.
    Токены следует передавать в заголовке `Authorization: Bearer <access_token>` для доступа к защищённым ресурсам.

    Returns:
        TokenResponse: access_token и refresh_token
    """
    service = AuthService(db, redis)
    user = await service.register(user_data)

    # Сразу выполняем вход после регистрации
    access, refresh = await service.login(
        user=user,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host,
    )
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Аутентификация пользователя",
    description="Проверяет логин и пароль. При успехе возвращает access и refresh токены.",
    responses={
        200: {"description": "Успешный вход, возвращены токены"},
        401: {"description": "Неверный логин или пароль"},
        422: {"description": "Ошибка валидации (например, пустой пароль)"},
    },
)
async def login(
    login_data: UserLogin,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    _: Annotated[None, Depends(
        rate_limit(
            requests=settings.login_rate_limit_requests,  # макс. попыток входа за время period
            period=settings.login_rate_limit_period,
        ),
    )],
):
    """Вход в аккаунт."""
    service = AuthService(db, redis)
    user = await service.authenticate(login_data.login, login_data.password)
    access, refresh = await service.login(
        user=user,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host,
    )
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление access-токена",
    description="Позволяет получить новый access-токен, используя действительный refresh-токен. "
    "   Refresh-токен при этом остаётся прежним.",
    responses={
        200: {"description": "Новый access-токен успешно выдан"},
        401: {"description": "Недействительный или просроченный refresh-токен"},
        422: {"description": "Ошибка валидации (например, пустой токен)"},
             })
async def refresh(
    refresh_data: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    """Обновление access-токена с помощью refresh-токена."""
    new_access = await AuthService(db, redis).refresh(
        refresh_token=refresh_data.refresh_token,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host,
    )
    return TokenResponse(access_token=new_access, refresh_token=refresh_data.refresh_token)


@router.post(
    "/logout",
    summary="Выход с текущего устройства",
    description="Удаляет refresh-токен, связанный с текущим устройством. "
    "   После этого для обновления access-токена потребуется повторный вход.",
    responses={
        200: {"description": "Успешный выход"},
        401: {"description": "Неавторизован или неверный refresh-токен"},
    },
)
async def logout(
    refresh_data: RefreshRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    """Выход из текущего устройства (удаление refresh-токена)."""
    await AuthService(db, redis).logout(refresh_data.refresh_token, str(current_user.id))
    return {"message": "Logged out successfully"}


@router.post(
    "/logout-all",
    summary="Выход со всех устройств",
    description="Удаляет все refresh-токены пользователя. Все активные сессии становятся недействительными.",
    responses={
        200: {"description": "Все устройства разлогинены"},
        401: {"description": "Неавторизован"},
    },
)
async def logout_all(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    """Выход из всех устройств (удаление всех refresh-токенов пользователя)."""
    await AuthService(db, redis).logout_all(str(current_user.id))
    return {"message": "Logged out from all devices"}


@router.get(
    "/history",
    response_model=list[LoginHistoryResponse],
    summary="История входов пользователя",
    description="Возвращает список записей о входах текущего пользователя с пагинацией.",
)
async def login_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    limit: Annotated[int, Query(ge=1, le=100, description="Количество записей на странице")] = 20,
    offset: Annotated[int, Query(ge=0, description="Смещение от начала списка")] = 0,
):
    """Получение истории входов пользователя."""
    return await AuthService(db, redis).get_login_history(str(current_user.id), limit, offset)


@router.post(
    "/change-password",
    summary="Смена пароля",
    description="Позволяет авторизованному пользователю изменить свой пароль."
    "Требуется указать старый пароль для подтверждения.",
    responses={
        200: {"description": "Пароль успешно изменён"},
        400: {"description": "Неверный старый пароль или новый пароль слишком короткий"},
        401: {"description": "Неавторизован"},
    },
)
async def change_password(
    passwords: PasswordChange,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    """Смена пароля (требуется старый пароль)."""
    # Проверяем старый пароль через authenticate (кинет исключение, если неверен)
    await AuthService(db, redis).authenticate(current_user.login, passwords.old_password)
    # Меняем пароль
    await UserService(db, redis).update_password(current_user.id, passwords.new_password)
    # удалить все refresh-токены
    await AuthService(db, redis).logout_all(str(current_user.id))
    return {"message": "Password changed successfully"}


@router.patch(
    "/change-login",
    summary="Изменение логина",
    responses={
        200: {"description": "Логин успешно изменён"},
        400: {"description": "Неверный пароль или логин уже занят"},
        401: {"description": "Неавторизован (токен отсутствует или недействителен)"},
        403: {"description": "Доступ запрещён (недостаточно прав)"},
    },
)
async def change_login(
    login_data: LoginChange,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
):
    """
    Изменяет логин текущего пользователя.

    **Требуется авторизация** (access token в заголовке).

    - **new_login**: новый логин (должен быть уникальным)
    - **password**: текущий пароль для подтверждения

    Возможные ошибки:
    - `400` — неверный пароль или новый логин уже занят
    - `401` — отсутствует или недействителен токен

    Returns:
        dict
    """
    await UserService(db, redis).update_login(
        user_id=current_user.id,
        new_login=login_data.new_login,
        password=login_data.password,
    )
    return {"message": "Login changed successfully"}

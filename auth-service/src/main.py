import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from src.api.v1 import auth, oauth, roles, users
from src.core.config import settings
from src.core.exceptions import InputValidationError
from src.db import redis as redis_db


logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.2,
            environment="development" if settings.debug else "production",
        )
    except Exception:
        logger.exception("Failed to initialize Sentry. Continuing without error tracking.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Startup
    app.state.redis = await redis_db.create_redis_client()

    logger.info("Application started")
    logger.info(f"Redis connection: {settings.redis_host}:{settings.redis_port}")
    logger.info(f"Logging level: {logger.level}")

    yield

    # Shutdown
    await app.state.redis.aclose()
    logger.info("Application stopped")


tags_metadata = [
    {
        "name": "auth",
        "description": "Регистрация, аутентификация, управление сессиями.",
    },
    {
        "name": "users",
        "description": "Управление пользователями (профили, права, роли).",
    },
    {
        "name": "roles",
        "description": "CRUD для ролей (только для суперпользователя).",
    },
]

app = FastAPI(
    title=settings.project_name,
    description="""
    ## Асинхронное API для управления авторизацией

    ### Возможности:
    * Регистрация и вход (JWT access + refresh токены)
    * Управление ролями и назначение их пользователям
    * История входов
    * Выход с одного или всех устройств
    * Проверка прав доступа к ресурсам

    **Авторизация:**
        для защищённых эндпоинтов требуется передавать `access_token` в заголовке `Authorization: Bearer <token>`.
    """,
    version='0.1.0',
    docs_url='/auth/docs',
    openapi_url='/auth/openapi.json',
    openapi_tags=tags_metadata,
    servers=[
        {"url": "/auth", "description": "Базовый путь сервиса авторизации"},
    ],
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):  # noqa: RUF029
    """Логирование ошибок валидации и преобразование в кастомное исключение."""
    logger.warning("Input validation error: %s", exc.errors())
    # Поднимаем кастомное исключение, оно будет перехвачено и возвращено как ответ
    raise InputValidationError(details={"errors": exc.errors()})


@app.get('/auth/health')
async def health_check():
    """Health check endpoint."""
    return {'status': 'ok'}


@app.get('/auth/sentry-debug')
async def sentry_debug():
    """Намеренно падает, чтобы проверить интеграцию Sentry."""
    raise RuntimeError("auth-service: Sentry debug error")


app.include_router(auth.router)
app.include_router(roles.router)
app.include_router(users.router)
app.include_router(oauth.router)

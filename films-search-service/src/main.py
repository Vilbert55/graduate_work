import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from redis.asyncio import Redis

from src.api.v1 import films
from src.core.config import settings
from src.db import elastic, redis


logger = logging.getLogger(__name__)
RS_CACHE_EXPIRE_IN_SECONDS = 30  # хранение http-ответов в redis, в сек

if settings.sentry_dsn:
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.2,
        )
    except Exception:
        logger.exception("Failed to initialize Sentry. Continuing without error tracking.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Startup
    app.state.redis = await redis.get_redis_client()
    app.state.elastic = await elastic.get_elastic_client()

    logger.info("Application started")
    logger.info(f"Redis connection: {settings.redis_host}:{settings.redis_port}")
    logger.info(f"Elasticsearch connection: {settings.elastic_host}:{settings.elastic_port}")
    logger.info(f"Logging level: {logger.level}")

    yield

    # Shutdown
    await app.state.redis.aclose()
    await app.state.elastic.close()
    logger.info("Application stopped")


def configure_tracer() -> None:
    resource = Resource(attributes={
        SERVICE_NAME: "movies-films-search-service",
    })
    provider = TracerProvider(resource=resource)

    # OTLP экспортёр в Jaeger (gRPC)
    otlp_exporter = OTLPSpanExporter(endpoint="movies-jaeger:4317", insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Для отладки вывод в консоль
    # provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)


configure_tracer()


app = FastAPI(
    title=settings.project_name,
    description="""
    ## Асинхронное API для поиска фильмов

    ### Документация:
    - **Swagger UI**: [/films-search/api/docs](/films-search/api/docs)
    - **OpenAPI спецификация**: [/films-search/api/openapi.json](/films-search/api/openapi.json)
    """,
    version='1.5.0',
    docs_url='/films-search/api/docs',
    openapi_url='/films-search/api/openapi.json',
    default_response_class=JSONResponse,
    lifespan=lifespan,
)


def server_request_hook(span, scope):
    """Добавляет X-Request-Id в качестве атрибута спана."""
    # Ищем заголовок X-Request-Id в ASGI scope
    headers = scope.get("headers", [])
    for key, value in headers:
        if key == b"x-request-id":
            request_id = value.decode()
            span.set_attribute("http.request_id", request_id)
            break


FastAPIInstrumentor.instrument_app(
    app,
    server_request_hook=server_request_hook,
)


def _generate_cache_key(request: Request) -> str:
    """Сгенерировать ключ для кэша на основе запроса.

    Args:
        request (Request): объект запроса FastAPI

    Returns:
        str: хеш-сумма (md5) всего запроса
    """
    query_string = str(sorted(request.query_params.items()))
    key_data = f"{request.method}:{request.url.path}:{query_string}"

    key_hash = hashlib.md5(key_data.encode()).hexdigest()  # noqa: S324
    cache_key = f"cache:{key_hash}"

    logger.debug(f"Generated cache key: {cache_key} for path: {request.url.path}")
    return cache_key


def _should_cache_request(request: Request) -> bool:
    """Определить, нужно ли кэшировать этот запрос."""
    # Не кэшируем не-GET запросы
    if request.method != "GET":
        logger.debug(f"Skipping cache for non-GET request: {request.method} {request.url.path}")
        return False

    # Эндпоинты, которые не нужно кэшировать
    no_cache_endpoints = {
        "/films-search/api/health",
        "/films-search/api/openapi",
        "/films-search/api/openapi.json",
        "/films-search/api/docs",
        "/docs",
        "/redoc",
    }

    if request.url.path in no_cache_endpoints:
        logger.debug(f"Skipping cache for endpoint: {request.url.path}")
        return False

    return True


@app.middleware("http")
async def cache_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Middleware для кэширования ответов API."""
    logger.debug(f"Processing request: {request.method} {request.url.path}")

    if not _should_cache_request(request):
        return await call_next(request)

    redis_client: Redis = request.app.state.redis
    cache_key = _generate_cache_key(request)

    cached_response: str | None = await redis_client.get(cache_key)

    if cached_response:
        logger.info(f"Cache HIT: {request.method} {request.url.path}")

        try:
            data = json.loads(cached_response)
            return Response(
                content=data["content"],
                status_code=data["status_code"],
                headers=data["headers"],
                media_type=data.get("media_type", "application/json"),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Error parsing cached response: %s, key: %s", e, cache_key)  # noqa: TRY400
            # Если ошибка парсинга, продолжаем без кэша

    logger.info(f"Cache MISS: {request.method} {request.url.path}")

    # Получаем оригинальный ответ
    response = await call_next(request)

    # Если ответ успешный - кэшируем и возвращаем копию с сохраненным телом
    if 200 <= response.status_code < 300:  # noqa: PLR2004
        # Читаем тело ответа один раз и сохраняем его
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        # Получаем media_type из response, если None - берем из заголовков
        media_type = response.media_type
        if media_type is None:
            media_type = response.headers.get("content-type", "application/json")

        # Сохраняем в кэш в фоне
        background_tasks = BackgroundTasks()
        background_tasks.add_task(
            _save_body_to_cache,
            redis_client,
            cache_key,
            body,
            response.status_code,
            dict(response.headers),
            media_type,
            request.url.path,
        )

        # Возвращаем новый ответ с сохраненным телом
        return Response(
            content=body,
            status_code=response.status_code,
            headers=response.headers,
            media_type=media_type,
            background=background_tasks,
        )

    return response


async def _save_body_to_cache(  # noqa: PLR0913, PLR0917
    redis_client: Redis,
    cache_key: str,
    body: bytes,
    status_code: int,
    headers: dict,
    media_type: str,
    path: str,
) -> None:
    """Сохранить ответ в Redis кэш."""
    try:
        body_content: str = body.decode('utf-8')
    except UnicodeDecodeError as e:
        logger.error("Non-UTF8 response for %s: %s", path, e)  # noqa: TRY400
        return

    cache_data = {
        "content": body_content,
        "status_code": status_code,
        "headers": headers,
        "media_type": media_type,
    }

    await redis_client.set(
        cache_key,
        json.dumps(cache_data),
        RS_CACHE_EXPIRE_IN_SECONDS,
    )

    logger.debug(f"Cache SAVED: {path} (size: {len(body)} bytes)")


@app.get('/films-search/api/health')
async def health_check():
    """Health check endpoint."""
    return {'status': 'ok'}


@app.get('/films-search/api/sentry-debug')
async def sentry_debug():
    """Намеренно падает, чтобы проверить интеграцию Sentry."""
    raise RuntimeError("films-search-service: Sentry debug error")


# Подключаем роутер к серверу
app.include_router(films.router, prefix='/films-search/api/v1/films', tags=['films'])

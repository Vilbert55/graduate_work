import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.api.v1 import bookmarks, likes, reviews
from src.core.config import settings
from src.db.postgres import engine


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Управление жизненным циклом приложения."""
    if settings.sentry_dsn:
        try:
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                traces_sample_rate=0.2,
                environment="development" if settings.debug else "production",
            )
        except Exception:
            logger.exception("Failed to initialize Sentry. Continuing without error tracking.")

    logger.info("Application started")
    logger.info(f"PostgreSQL connection: {settings.postgres_host}:{settings.postgres_port}")
    logger.info(f"Logging level: {logger.level}")

    yield

    await engine.dispose()
    logger.info("Application stopped")


def configure_tracer() -> None:
    """Настроить OpenTelemetry-трейсер для экспорта в Jaeger (OTLP gRPC)."""
    resource = Resource(attributes={
        SERVICE_NAME: "movies-community-content-service",
    })
    provider = TracerProvider(resource=resource)

    otlp_exporter = OTLPSpanExporter(endpoint=settings.jaeger_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    trace.set_tracer_provider(provider)


configure_tracer()


app = FastAPI(
    title=settings.project_name,
    description="""
    ## API пользовательского контента

    Закладки, оценки и рецензии на фильмы.

    ### Документация:
    - **Swagger UI**: [/community-content/api/docs](/community-content/api/docs)
    - **OpenAPI спецификация**: [/community-content/api/openapi.json](/community-content/api/openapi.json)
    """,
    version='1.0.0',
    docs_url='/community-content/api/docs',
    openapi_url='/community-content/api/openapi.json',
    default_response_class=JSONResponse,
    lifespan=lifespan,
)


def server_request_hook(span, scope):
    """Добавляет X-Request-Id в качестве атрибута спана."""
    headers = scope.get("headers", [])
    for key, value in headers:
        if key == b"x-request-id":
            span.set_attribute("http.request_id", value.decode())
            break


FastAPIInstrumentor.instrument_app(
    app,
    server_request_hook=server_request_hook,
)


@app.get('/community-content/api/health')
async def health_check():
    """Health check endpoint."""
    return {'status': 'ok'}


@app.get('/community-content/api/sentry-debug')
async def sentry_debug():
    """Намеренно падает, чтобы проверить интеграцию Sentry."""
    raise RuntimeError("community-content-service: Sentry debug error")


app.include_router(bookmarks.router, prefix='/community-content/api/v1/bookmarks', tags=['bookmarks'])
app.include_router(likes.router, prefix='/community-content/api/v1/likes', tags=['likes'])
app.include_router(reviews.router, prefix='/community-content/api/v1/reviews', tags=['reviews'])

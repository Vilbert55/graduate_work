import logging
from typing import Never
from uuid import UUID

import sentry_sdk
from apiflask import APIFlask, abort
from flask import g, request
from sentry_sdk.integrations.flask import FlaskIntegration

from src.apache_kafka.producer import get_producer
from src.api.v1.events import auth_function
from src.api.v1.events import bp as events_bp
from src.api.v1.track import bp as track_bp
from src.core.config import settings


logger = logging.getLogger(__name__)


def create_app() -> APIFlask:  # noqa: C901
    """Создать и настроить экземпляр APIFlask-приложения.

    Returns:
        APIFlask: настроенное приложение с готовыми эндпоинтами UGC API.
    """
    if settings.sentry_dsn:
        try:
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                integrations=[FlaskIntegration()],
                traces_sample_rate=0.2,
                environment="development" if settings.debug else "production",
            )
        except Exception:
            logger.exception("Failed to initialize Sentry. Continuing without error tracking.")

    app = APIFlask(__name__)

    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024   # 64 KB
    app.config['OPENAPI_VERSION'] = '3.0.3'
    app.config['TITLE'] = 'UGC API'
    app.config['VERSION'] = '1.0'
    app.config['DESCRIPTION'] = (
        'Сервис сбора пользовательских действий: клики, просмотры, произвольные события.'
    )
    app.config['DOCS_URL'] = '/ugc/docs'

    # Настройка безопасности для Swagger UI
    app.config['SECURITY_SCHEMES'] = {
        'BearerAuth': {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': 'Введите JWT-токен, полученный от auth-сервиса',
        },
    }
    app.config['SECURITY_REQUIREMENTS'] = [{'BearerAuth': []}]

    @app.before_request
    def extract_request_id() -> None:
        """Извлечь и проверить X-Request-Id для всех запросов к API."""
        if not request.path.startswith('/ugc/api/v1'):
            return
        raw_id = request.headers.get('X-Request-Id')
        if not raw_id:
            abort(400, message='Missing X-Request-Id header')
        try:
            g.request_id = UUID(raw_id)
        except ValueError:
            abort(400, message='Invalid X-Request-Id header: must be a valid UUID')

    @app.before_request
    def authenticate_user() -> None:
        """Проверка JWT для маршрутов блюпринта events."""
        if request.blueprint == 'events':
            auth_function()

    app.register_blueprint(events_bp)
    app.register_blueprint(track_bp)

    # --- Sentry debug ---
    @app.get('/ugc/sentry-debug')
    def sentry_debug() -> Never:
        """Намеренно падает, чтобы проверить интеграцию Sentry."""
        raise RuntimeError("activity-tracker-service: Sentry debug error")

    # --- Health checks ---
    @app.get('/ugc/health/live')
    def liveness() -> dict[str, str]:
        """Проверка, что процесс жив (всегда 200)."""
        return {'status': 'alive'}, 200

    @app.get('/ugc/health/ready')
    def readiness() -> tuple[dict[str, str], int]:
        """Проверка готовности сервиса принимать трафик (проверяет связь с Kafka)."""
        try:
            producer = get_producer()
            producer.partitions_for('custom_events')
        except Exception:
            logger.exception('Readiness check failed')
            return {'status': 'not ready', 'error': 'Kafka not reachable'}, 503
        else:
            return {'status': 'ready'}, 200

    return app

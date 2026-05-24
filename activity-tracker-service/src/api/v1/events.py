import logging
from datetime import UTC, datetime
from uuid import UUID

import jwt
from apiflask import APIBlueprint, abort
from apiflask.fields import String
from flask import g, request
from pydantic import ValidationError

from src.apache_kafka.producer import send_event
from src.core.config import settings
from src.models.events import (
    EventInput,
    EventInputClick,
    EventInputCustom,
    EventInputView,
    EventReport,
    EventReportClick,
    EventReportCustom,
    EventReportView,
)


logger = logging.getLogger(__name__)

# Создание Blueprint - аналог Namespace
bp = APIBlueprint('events', __name__, url_prefix='/ugc/api/v1/events')


# --- Схемы для документации (на основе Pydantic) ---

@bp.post('/click', endpoint='post_click')
@bp.input(EventInputClick, location='json')
@bp.output({'status': String()}, status_code=202)
def post_click(json_data: EventInputClick):
    """Принять событие клика."""
    return _send_and_respond(json_data, EventReportClick, settings.kafka_topic_clicks)


@bp.post('/view', endpoint='post_view')
@bp.input(EventInputView, location='json')
@bp.output({'status': String()}, status_code=202)
def post_view(json_data: EventInputView):
    """Принять событие просмотра."""
    return _send_and_respond(json_data, EventReportView, settings.kafka_topic_views)


@bp.post('/custom', endpoint='post_custom')
@bp.input(EventInputCustom, location='json')
@bp.output({'status': String()}, status_code=202)
def post_custom(json_data: EventInputCustom):
    """Принять кастомное событие."""
    return _send_and_respond(json_data, EventReportCustom, settings.kafka_topic_custom)


def _send_and_respond(input_data: EventInput, report_model_cls: type[EventReport], topic: str) -> dict[str, str]:
    """
    Валидирует данные, добавляет request_id, user_id, server_timestamp и отправляет в Kafka.
    При ошибках валидации — 422, при недоступности Kafka — 503.

    Args:
        input_data: экземпляр модели EventInput, тело запроса
        report_model_cls (type[EventReport]): Модель pydantic для отправкии сообщения в брокер
        topic (str): имя топика куда отправлять

    Returns:
        dict: {"status": "accepted"}
    """
    data = input_data.model_dump()
    data['request_id'] = g.get('request_id')
    try:
        event = report_model_cls.model_validate(data)
    except ValidationError as e:
        abort(422, message=e.errors())
    event_data = event.model_dump(mode='json')
    event_data['user_id'] = str(g.user_id)
    event_data['server_timestamp'] = datetime.now(UTC).isoformat()
    try:
        send_event(topic, event_data, key=event_data['user_id'])
    except Exception:
        logger.exception("Failed to publish event to Kafka")
        abort(503, message="Kafka unavailable")
    return {"status": "accepted"}


def auth_function():
    """Проверяет JWT в заголовке Authorization, извлекает user_id и кладёт в g.user_id.
    При любой ошибке аутентификации возвращает 401.
    """
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        abort(401, message='Missing or invalid Authorization header')
    token = auth_header[7:]
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={'require': ['exp', 'sub']},
        )
        user_id_str = payload.get('sub')
        if not user_id_str:
            abort(401, message='Token has no sub')
        try:
            g.user_id = UUID(user_id_str)
        except ValueError:
            abort(401, message='Invalid user_id format')
    except jwt.ExpiredSignatureError:
        abort(401, message='Token expired')
    except jwt.InvalidTokenError:
        abort(401, message='Invalid token')

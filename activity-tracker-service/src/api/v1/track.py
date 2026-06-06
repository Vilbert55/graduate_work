"""Публичная ссылка из писем (замыкание петли без авторизации).

Ссылка вшита в письмо win-back: пользователь кликает её в почте, браузер делает
GET, и мы публикуем событие recommendation (action=clicked) в Kafka — оттуда оно
Routine Load'ом попадает в user_events. Так клик из настоящего письма виден в
Superset (mv_rule_conversion), без синтетических событий.

Идемпотентность: request_id события детерминирован — uuid5 от (rule, run, user),
где run — идентификатор конкретного срабатывания правила. Повторный клик по той же
ссылке даёт тот же ключ и схлопывается в одну строку user_events (PRIMARY KEY
(request_id, event_type)) — сколько ни кликай одно письмо, переход один. При этом
новое срабатывание правила несёт новый run -> новую ссылку -> отдельный переход
(письма старого и нового запусков не задваиваются). recovery идёт с тем же run,
поэтому ссылка та же.

Эндпоинт ПУБЛИЧНЫЙ (получатель письма не авторизован в браузере) и лежит вне
/ugc/api/v1, поэтому JWT и X-Request-Id здесь не нужны. Параметры не подписаны —
упрощение для демо; в проде ссылку надо подписывать (HMAC + срок годности),
иначе переход можно подделать.
"""
import logging
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from apiflask import APIBlueprint
from flask import Response, request

from src.apache_kafka.producer import send_event
from src.core.config import settings


logger = logging.getLogger(__name__)

bp = APIBlueprint('track', __name__, url_prefix='/ugc')

_THANKS_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Movies</title></head>
<body style="font-family:sans-serif;text-align:center;margin-top:12%">
<h2>Спасибо! Уже подбираем для вас фильмы.</h2>
<p>Можно вернуться в почту и закрыть эту вкладку.</p>
</body></html>"""


def _valid_uuid(value: str | None) -> str | None:
    """Вернуть value, если это корректный UUID, иначе None."""
    if not value:
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


@bp.get('/email/click', endpoint='email_click')
def email_click() -> Response:
    """Клик по ссылке из письма правила — публикуем переход (recommendation) в Kafka."""
    rule_code = request.args.get('rule')
    user_id = _valid_uuid(request.args.get('user'))
    if not rule_code or not user_id:
        return Response('Неверная ссылка', status=400, mimetype='text/plain; charset=utf-8')

    run_id = request.args.get('run', '')
    now = datetime.now(UTC).isoformat()
    event = {
        # детерминированный id перехода: повтор того же письма не задвоится, а новое
        # срабатывание правила (другой run) даёт отдельный переход
        'request_id': str(uuid5(NAMESPACE_URL, f'{rule_code}:{run_id}:{user_id}')),
        'user_id': user_id,
        'rule_code': rule_code,
        'action': 'clicked',
        'timestamp': now,
        'server_timestamp': now,
    }
    try:
        send_event(settings.kafka_topic_recommendations, event, key=user_id)
    except Exception:
        logger.exception('Failed to publish recommendation click')
        return Response('Сервис временно недоступен', status=503, mimetype='text/plain; charset=utf-8')

    return Response(_THANKS_HTML, status=200, mimetype='text/html; charset=utf-8')

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


PAYLOAD_MAX_SIZE = 8132  # байт


class EventInput(BaseModel):
    """Базовый класс тела запроса о пользовательском событии"""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EventReport(BaseModel):
    """Базовый класс отчёта о пользовательском событии (сообщение для брокера)"""
    request_id: UUID = Field(description="X-Request-Id для всех запросов к API, генерирует Nginx.")


class EventInputClick(EventInput):
    """Ввод события клика"""
    element_id: str
    page: str


class EventInputView(EventInput):
    """Ввод события просмотра"""
    film_id: UUID
    progress_seconds: int


class EventInputCustom(EventInput):
    """Ввод кастомного события"""
    event_type: str
    payload: dict[str, Any]

    @field_validator('payload')
    @classmethod
    def validate_payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, separators=(',', ':'))) > PAYLOAD_MAX_SIZE:
            raise ValueError(f'payload must not exceed {PAYLOAD_MAX_SIZE} bytes when serialized')
        return v


class EventInputRecommendation(EventInput):
    """Реакция пользователя на письмо/уведомление, порождённое правилом alerting-service.

    Замыкает контур событий: правило → задача в notifications → письмо → клик
    пользователя → факт обратно в StarRocks. Аналитик в Superset может посчитать
    конверсию своих собственных правил.
    """
    rule_code: str = Field(description="Код правила alerting, породившего рекомендацию.")
    notification_message_id: UUID = Field(description="ID сообщения из notifications.t_messages.")
    action: str = Field(description="Действие пользователя: opened | clicked | dismissed.")
    film_id: UUID | None = Field(default=None, description="Фильм, на который вёл клик (если применимо).")

    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in {'opened', 'clicked', 'dismissed'}:
            raise ValueError("action must be one of: opened, clicked, dismissed")
        return v


class EventReportClick(EventInputClick, EventReport):
    """Отчёт о клике"""


class EventReportView(EventInputView, EventReport):
    """Отчёт о просмотре"""


class EventReportCustom(EventInputCustom, EventReport):
    """Отчёт кастомный"""


class EventReportRecommendation(EventInputRecommendation, EventReport):
    """Отчёт о реакции на рекомендацию"""

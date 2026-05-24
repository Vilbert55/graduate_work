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


class EventReportClick(EventInputClick, EventReport):
    """Отчёт о клике"""


class EventReportView(EventInputView, EventReport):
    """Отчёт о просмотре"""


class EventReportCustom(EventInputCustom, EventReport):
    """Отчёт кастомный"""

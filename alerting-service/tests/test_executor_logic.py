"""Юнит-тесты чистой бизнес-логики движка (НФТ-6): разбор контракта колонок
SQL-правила, парсинг per-user context, двухуровневый frequency cap.

Запуск:  cd alerting-service && poetry run pytest -v
"""
import uuid

import pytest

from src.services.executor import (
    _coerce_cap,
    _extract_audience,
    _filter_by_cap,
    _parse_context,
)


# ---------------------------------------------------------------------------
# Контракт колонок: SQL правила обязан вернуть user_id, опционально context (ФТ-2)
# ---------------------------------------------------------------------------

class TestExtractAudience:
    def test_user_id_with_context(self):
        rows = [{"user_id": "u1", "context": '{"top_genres": ["Drama"]}'}]
        assert _extract_audience(rows) == [("u1", {"top_genres": ["Drama"]})]

    def test_user_id_without_context(self):
        assert _extract_audience([{"user_id": "u1"}]) == [("u1", None)]

    def test_missing_user_id_column_raises(self):
        # Нарушение контракта = ошибка SQL правила (обработка ошибок, НФТ-6).
        with pytest.raises(ValueError, match="user_id"):
            _extract_audience([{"film_id": "f1"}])

    def test_dedup_by_user_id_keeps_first(self):
        rows = [
            {"user_id": "u1", "context": '{"a": 1}'},
            {"user_id": "u1", "context": '{"a": 2}'},
        ]
        assert _extract_audience(rows) == [("u1", {"a": 1})]

    def test_skips_null_user_id(self):
        rows = [{"user_id": None}, {"user_id": "u2"}]
        assert _extract_audience(rows) == [("u2", None)]

    def test_uuid_user_id_stringified(self):
        u = uuid.uuid4()
        assert _extract_audience([{"user_id": u}]) == [(str(u), None)]


# ---------------------------------------------------------------------------
# Разбор per-user context (StarRocks отдаёт JSON строкой)
# ---------------------------------------------------------------------------

class TestParseContext:
    def test_json_string_object(self):
        assert _parse_context('{"x": 1}') == {"x": 1}

    def test_none(self):
        assert _parse_context(None) is None

    def test_dict_passthrough(self):
        assert _parse_context({"x": 1}) == {"x": 1}

    def test_non_object_json_is_none(self):
        assert _parse_context("[1, 2, 3]") is None

    def test_invalid_json_is_none(self):
        assert _parse_context("not-json") is None


# ---------------------------------------------------------------------------
# Frequency cap (ФТ-3): чистый фильтр + нормализация конфигурации
# ---------------------------------------------------------------------------

class TestFilterByCap:
    def test_removes_blocked_preserving_context(self):
        audience = [("u1", None), ("u2", {"a": 1}), ("u3", None)]
        assert _filter_by_cap(audience, {"u2"}) == [("u1", None), ("u3", None)]

    def test_empty_blocked_keeps_all(self):
        audience = [("u1", {"a": 1})]
        assert _filter_by_cap(audience, set()) == audience

    def test_all_blocked(self):
        assert _filter_by_cap([("u1", None)], {"u1"}) == []


class TestCoerceCap:
    def test_json_string(self):
        assert _coerce_cap('{"per_user_per_day": 1}') == {"per_user_per_day": 1}

    def test_none_is_empty(self):
        assert _coerce_cap(None) == {}

    def test_empty_string_is_empty(self):
        assert _coerce_cap("") == {}

    def test_dict_passthrough(self):
        assert _coerce_cap({"per_rule_per_user_days": 30}) == {"per_rule_per_user_days": 30}

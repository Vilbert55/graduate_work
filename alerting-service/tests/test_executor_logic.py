"""Юнит-тесты чистой бизнес-логики движка: разбор контракта колонок SQL-правила,
парсинг per-user context, разбор настроек и фильтр frequency cap.

Запуск:  cd alerting-service && poetry run pytest -v
"""
import uuid

import pytest

from src.services.executor import (
    FrequencyCap,
    _extract_audience,
    _filter_by_cap,
    _parse_context,
    _pos_int_or_none,
    _truncate_to_max,
)


# Контракт колонок: SQL правила обязан вернуть user_id, опционально context.

class TestExtractAudience:
    def test_user_id_with_context(self):
        rows = [{"user_id": "u1", "context": '{"top_genres": ["Drama"]}'}]
        assert _extract_audience(rows) == [("u1", {"top_genres": ["Drama"]})]

    def test_user_id_without_context(self):
        assert _extract_audience([{"user_id": "u1"}]) == [("u1", None)]

    def test_missing_user_id_column_raises(self):
        # Нарушение контракта = ошибка SQL правила, которую движок ловит и логирует.
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


# Разбор per-user context (StarRocks отдаёт JSON строкой).

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


# Frequency cap: чистый фильтр аудитории.

class TestFilterByCap:
    def test_removes_blocked_preserving_context(self):
        audience = [("u1", None), ("u2", {"a": 1}), ("u3", None)]
        assert _filter_by_cap(audience, {"u2"}) == [("u1", None), ("u3", None)]

    def test_empty_blocked_keeps_all(self):
        audience = [("u1", {"a": 1})]
        assert _filter_by_cap(audience, set()) == audience

    def test_all_blocked(self):
        assert _filter_by_cap([("u1", None)], {"u1"}) == []


# Frequency cap: разбор настроек. per_rule_per_user_days — из правила,
# per_user_per_day — глобальная настройка движка (не из правила).

class TestFrequencyCap:
    def test_per_rule_from_json_string(self):
        cap = FrequencyCap.build('{"per_rule_per_user_days": 30}', 0)
        assert cap == FrequencyCap(per_rule_per_user_days=30, per_user_per_day=None)

    def test_per_rule_from_dict(self):
        cap = FrequencyCap.build({"per_rule_per_user_days": 30}, 0)
        assert cap.per_rule_per_user_days == 30

    def test_global_per_user_per_day(self):
        cap = FrequencyCap.build({}, 3)
        assert cap == FrequencyCap(per_rule_per_user_days=None, per_user_per_day=3)

    def test_rule_per_user_per_day_is_ignored(self):
        # per_user_per_day — общий потолок, берётся только из настройки движка;
        # одноимённый ключ в правиле игнорируется.
        cap = FrequencyCap.build({"per_user_per_day": 99}, 0)
        assert cap.per_user_per_day is None

    def test_none_is_empty(self):
        cap = FrequencyCap.build(None, 0)
        assert cap.is_empty

    def test_empty_string_is_empty(self):
        assert FrequencyCap.build("", 0).is_empty

    def test_zero_global_disables_level(self):
        assert FrequencyCap.build({}, 0).per_user_per_day is None

    def test_both_levels(self):
        cap = FrequencyCap.build({"per_rule_per_user_days": 7}, 3)
        assert (cap.per_rule_per_user_days, cap.per_user_per_day) == (7, 3)
        assert not cap.is_empty


# Усечение аудитории до потолка правила (max_users).

class TestTruncateToMax:
    def test_under_limit_unchanged(self):
        audience = [("u1", None), ("u2", None)]
        assert _truncate_to_max(audience, 5) == audience

    def test_equal_limit_unchanged(self):
        audience = [("u1", None), ("u2", None)]
        assert _truncate_to_max(audience, 2) == audience

    def test_over_limit_truncated_in_order(self):
        audience = [("u1", None), ("u2", None), ("u3", None)]
        assert _truncate_to_max(audience, 2) == [("u1", None), ("u2", None)]


# Разбор положительного целого (используется при сборке FrequencyCap).

class TestPosIntOrNone:
    def test_positive_int(self):
        assert _pos_int_or_none(5) == 5

    def test_zero_is_none(self):
        assert _pos_int_or_none(0) is None

    def test_negative_is_none(self):
        assert _pos_int_or_none(-3) is None

    def test_numeric_string(self):
        assert _pos_int_or_none("7") == 7

    def test_non_numeric_is_none(self):
        assert _pos_int_or_none("abc") is None

    def test_none_is_none(self):
        assert _pos_int_or_none(None) is None

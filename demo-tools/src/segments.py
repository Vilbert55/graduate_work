"""Возрастные полосы для демо-сегментов.

В auth.users возраст хранится как целое число (`age`). Но демо-сегмент
по-прежнему адресуется полосой вида `25-34` (логины `demo_<gender>_<band>_<country>_NNNN`,
параметр `--segment female_25-34_RU`, `segment_code` в dim_users).

Здесь — единственный источник правды о границах полос:
  - seed_users сэмплирует конкретный возраст внутри полосы;
  - trigger_events фильтрует юзеров по диапазону `age BETWEEN lo AND hi`.
Аналогичный CASE WHEN по тем же границам строит `segment_code` в StarRocks
(starrocks_dims_init/init.sql) — держать в синхроне.
"""
from __future__ import annotations

# Полоса -> (нижняя, верхняя) граница включительно.
AGE_BANDS: dict[str, tuple[int, int]] = {
    "18-24": (18, 24),
    "25-34": (25, 34),
    "35-44": (35, 44),
}


def band_range(band: str) -> tuple[int, int]:
    """Границы полосы; бросает KeyError на неизвестной полосе."""
    return AGE_BANDS[band]

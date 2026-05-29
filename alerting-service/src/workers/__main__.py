"""Точка входа alerting-engine.

Запуск:  python -m src.workers
"""
import asyncio
import logging
import sys

from pythonjsonlogger import jsonlogger

from src.core.config import settings
from src.workers.engine import run


def _setup_logging() -> None:
    """JSON-логи в stdout — едины с остальными сервисами проекта (ELK)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"levelname": "level", "asctime": "time", "name": "logger"},
    ))
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    root.handlers = [handler]


def _setup_sentry() -> None:
    if not settings.sentry_dsn:
        return
    import sentry_sdk
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.2)


def main() -> None:
    _setup_logging()
    _setup_sentry()
    asyncio.run(run())


if __name__ == "__main__":
    main()

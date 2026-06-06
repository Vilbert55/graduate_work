"""Юнит-тесты движка работают офлайн — без БД и StarRocks: проверяется чистая
бизнес-логика executor (контракт колонок, разбор context, frequency cap).

config.Settings требует POSTGRES_PASSWORD уже на импорте src.core.config,
поэтому задаём заглушку. Реальное соединение при этом не открывается:
create_async_engine ленив, StarRocks в этих тестах не вызывается.
"""
import os


os.environ.setdefault("POSTGRES_PASSWORD", "test")

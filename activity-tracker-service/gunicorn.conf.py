from typing import TYPE_CHECKING

from src.core.config import settings


if TYPE_CHECKING:
    from gunicorn.arbiter import Arbiter
    from gunicorn.workers.base import Worker

workers: int = settings.gunicorn_workers
worker_class: str = settings.gunicorn_worker_class
bind: str = f'{settings.server_host}:{settings.server_port}'
loglevel: str = settings.gunicorn_loglevel


def worker_exit(_server: 'Arbiter', _worker: 'Worker') -> None:
    """Гарантирует закрытие KafkaProducer при остановке воркера."""
    from src.apache_kafka.producer import close_producer
    close_producer()

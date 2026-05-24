import json
import logging
import os

from kafka import KafkaProducer
from kafka.errors import KafkaError
from kafka.producer.future import FutureRecordMetadata

from src.core.config import settings


logger = logging.getLogger(__name__)

_producer: KafkaProducer | None = None


def get_producer() -> KafkaProducer:
    """Возвращает глобальный экземпляр KafkaProducer (ленивая инициализация).

    Создаётся один раз при первом обращении внутри воркера.
    """
    global _producer  # noqa: PLW0603
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all',
            retries=3,
            max_in_flight_requests_per_connection=1,
            compression_type='gzip',
        )
        logger.info('KafkaProducer created for worker (pid=%d)', os.getpid())
    return _producer


def on_send_success(record_metadata: FutureRecordMetadata) -> None:
    """Callback при успешной доставке сообщения."""
    logger.debug(
        'Message delivered to topic=%s partition=%d offset=%d',
        record_metadata.topic,
        record_metadata.partition,
        record_metadata.offset,
    )


def on_send_error(exc: Exception) -> None:
    """Callback при ошибке отправки."""
    logger.error('Failed to deliver message to Kafka: %s', exc)


def send_event(topic: str, event: dict[str, object], key: str | None = None) -> None:
    """Опубликовать событие в указанный топик Kafka (асинхронно)."""
    producer = get_producer()
    try:
        future = producer.send(topic, value=event, key=key)
        future.add_callback(on_send_success)
        future.add_errback(on_send_error)
        logger.debug('Event placed in send buffer for topic=%s key=%s', topic, key)
    except Exception as e:
        logger.exception('Failed to enqueue event for topic=%s', topic)
        raise KafkaError(f'Failed to enqueue event: {e}') from e


def close_producer() -> None:
    """Закрыть продюсера (вызывается при завершении воркера)."""
    global _producer  # noqa: PLW0603
    if _producer is not None:
        _producer.flush(timeout=30)
        _producer.close()
        _producer = None
        logger.info("KafkaProducer closed and flushed.")

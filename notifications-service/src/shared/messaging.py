"""Константы топологии RabbitMQ.

Топология:
    exchange  notifications         (direct, durable)
    exchange  notifications.dlx     (direct, durable)
    queue     q.email   ── x-dead-letter-exchange=notifications.dlx
    queue     q.ws      ── x-dead-letter-exchange=notifications.dlx
    queue     q.dead    (свалка для сообщений, которые consumer отверг nack(requeue=False))

    bindings:
        notifications:email      -> q.email
        notifications:ws         -> q.ws
        notifications.dlx:email  -> q.dead
        notifications.dlx:ws     -> q.dead

Retry-механизм реализован через БД (next_attempt_at в notification_messages),
а не через TTL-retry-очередь в RabbitMQ. Это согласовано с outbox-паттерном:
БД — источник истины, RabbitMQ — только транспорт доставки.
"""

EXCHANGE_MAIN = "notifications"
EXCHANGE_DLX = "notifications.dlx"

QUEUE_EMAIL = "q.email"
QUEUE_WS = "q.ws"
QUEUE_DEAD = "q.dead"

ROUTING_KEY_EMAIL = "email"
ROUTING_KEY_WS = "ws"

CHANNEL_TO_ROUTING_KEY: dict[str, str] = {
    "email": ROUTING_KEY_EMAIL,
    "ws": ROUTING_KEY_WS,
}

CHANNEL_TO_QUEUE: dict[str, str] = {
    "email": QUEUE_EMAIL,
    "ws": QUEUE_WS,
}

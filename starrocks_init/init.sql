CREATE DATABASE IF NOT EXISTS ugc_analytics;

USE ugc_analytics;

-- Максимум одновременных Routine Load задач на один BE. Должно быть >= числу
-- Routine Load заданий ниже (сейчас их 4). Добавишь пятое — подними значение.
ADMIN SET FRONTEND CONFIG ("max_routine_load_task_num_per_be" = "4");

-- ------------------------------------------------------------------
-- user_events — Primary Key table.
-- PRIMARY KEY (request_id, event_type) даёт встроенную дедупликацию:
-- при повторной вставке (ретрай Routine Load, дубль продьюсера) StarRocks
-- выполняет REPLACE — остаётся одна строка. Не нужно отдельных шагов
-- дедупликации в правилах alerting-service.
--
-- enable_persistent_index=true — рекомендация StarRocks для PK-таблиц
-- с высоким write-throughput, держит индекс на диске вместо памяти.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_events (
    request_id        VARCHAR(64)      NOT NULL COMMENT 'Уникальный идентификатор запроса',
    event_type        VARCHAR(20)      NOT NULL COMMENT 'view | click | custom | recommendation',
    user_id           VARCHAR(36)      NOT NULL COMMENT 'UUID пользователя',
    client_time       DATETIME         NOT NULL COMMENT 'timestamp из клиента',
    server_time       DATETIME         NOT NULL COMMENT 'server_timestamp',
    ingestion_time    DATETIME         DEFAULT CURRENT_TIMESTAMP COMMENT 'время вставки в StarRocks',
    film_id           VARCHAR(36)      NULL,
    progress_seconds  INT              NULL,
    element_id        VARCHAR(255)     NULL,
    page              VARCHAR(255)     NULL,
    custom_event_type VARCHAR(100)     NULL COMMENT 'event_type из custom',
    rule_code         VARCHAR(64)      NULL COMMENT 'код правила alerting (для event_type=recommendation)',
    notification_message_id VARCHAR(36) NULL COMMENT 'notifications.t_messages.id (для event_type=recommendation)',
    action            VARCHAR(20)      NULL COMMENT 'opened | clicked | dismissed (для event_type=recommendation)',
    payload           JSON             NULL COMMENT 'произвольный JSON'
)
PRIMARY KEY (request_id, event_type)
DISTRIBUTED BY HASH(request_id) BUCKETS 10
PROPERTIES (
    -- в all-in-1 образе используется одиночный узел, поэтому replication_num = 1
    "replication_num" = "1",
    "enable_persistent_index" = "true"
);


-- ------------------------------------------------------------------
-- Routine Load: views / clicks / custom / recommendations.
-- Каждое задание читает свой Kafka-топик и пишет в user_events.
-- ------------------------------------------------------------------
CREATE ROUTINE LOAD ugc_analytics.views_load ON user_events
COLUMNS(
    user_id,
    film_id,
    progress_seconds,
    client_time,        -- берётся из jsonpaths
    server_time,        -- берётся из jsonpaths
    request_id,
    event_type = 'view' -- константное значение
)
PROPERTIES
(
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "20",
    "max_batch_rows" = "200000",
    "max_error_number" = "1000",
    "strict_mode" = "false",
    "format" = "json",
    "jsonpaths" = "[
        \"$.user_id\",
        \"$.film_id\",
        \"$.progress_seconds\",
        \"$.timestamp\",
        \"$.server_timestamp\",
        \"$.request_id\"
    ]"
)
FROM KAFKA
(
    "kafka_broker_list" = "movies-kafka:9092",
    "kafka_topic" = "views",
    "property.group.id" = "starrocks_views_consumer_v2",
    "property.client.id" = "starrocks_views_client",
    "property.enable.auto.commit" = "true",
    "property.auto.offset.reset" = "earliest"
);


CREATE ROUTINE LOAD ugc_analytics.clicks_load ON user_events
COLUMNS(
    user_id,
    element_id,
    page,
    client_time,         -- из $.timestamp
    server_time,         -- из $.server_timestamp
    request_id,
    event_type = 'click'
)
PROPERTIES
(
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "20",
    "max_batch_rows" = "200000",
    "max_error_number" = "1000",
    "strict_mode" = "false",
    "format" = "json",
    "jsonpaths" = "[
        \"$.user_id\",
        \"$.element_id\",
        \"$.page\",
        \"$.timestamp\",
        \"$.server_timestamp\",
        \"$.request_id\"
    ]"
)
FROM KAFKA
(
    "kafka_broker_list" = "movies-kafka:9092",
    "kafka_topic" = "clicks",
    "property.group.id" = "starrocks_clicks_consumer",
    "property.client.id" = "starrocks_clicks_client",
    "property.enable.auto.commit" = "true",
    "property.auto.offset.reset" = "earliest"
);


CREATE ROUTINE LOAD ugc_analytics.custom_load ON user_events
COLUMNS(
    user_id,
    custom_event_type,    -- поле $.event_type
    payload,              -- JSON, StarRocks распарсит автоматически
    client_time,          -- $.timestamp
    server_time,          -- $.server_timestamp
    request_id,
    event_type = 'custom'
)
PROPERTIES
(
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "20",
    "max_batch_rows" = "200000",
    "max_error_number" = "1000",
    "strict_mode" = "false",
    "format" = "json",
    "jsonpaths" = "[
        \"$.user_id\",
        \"$.event_type\",
        \"$.payload\",
        \"$.timestamp\",
        \"$.server_timestamp\",
        \"$.request_id\"
    ]"
)
FROM KAFKA
(
    "kafka_broker_list" = "movies-kafka:9092",
    "kafka_topic" = "custom_events",
    "property.group.id" = "starrocks_custom_consumer",
    "property.client.id" = "starrocks_custom_client",
    "property.enable.auto.commit" = "true",
    "property.auto.offset.reset" = "earliest"
);


-- Реакция пользователя на письма от alerting-service (см.
-- activity-tracker /ugc/api/v1/events/recommendation).
CREATE ROUTINE LOAD ugc_analytics.recommendations_load ON user_events
COLUMNS(
    user_id,
    rule_code,
    notification_message_id,
    action,
    film_id,
    client_time,                 -- $.timestamp
    server_time,                 -- $.server_timestamp
    request_id,
    event_type = 'recommendation'
)
PROPERTIES
(
    "desired_concurrent_number" = "1",
    "max_batch_interval" = "20",
    "max_batch_rows" = "200000",
    "max_error_number" = "1000",
    "strict_mode" = "false",
    "format" = "json",
    "jsonpaths" = "[
        \"$.user_id\",
        \"$.rule_code\",
        \"$.notification_message_id\",
        \"$.action\",
        \"$.film_id\",
        \"$.timestamp\",
        \"$.server_timestamp\",
        \"$.request_id\"
    ]"
)
FROM KAFKA
(
    "kafka_broker_list" = "movies-kafka:9092",
    "kafka_topic" = "recommendations",
    "property.group.id" = "starrocks_recommendations_consumer",
    "property.client.id" = "starrocks_recommendations_client",
    "property.enable.auto.commit" = "true",
    "property.auto.offset.reset" = "earliest"
);

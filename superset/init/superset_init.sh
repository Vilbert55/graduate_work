#!/bin/bash
# Init-логика Superset:
#   1) применить миграции метаданных
#   2) создать суперпользователя (если ещё нет)
#   3) зарегистрировать StarRocks как database "starrocks_analytics" (идемпотентно)
#   4) запустить webserver
set -e

echo "[superset-init] applying metadata migrations..."
superset db upgrade

echo "[superset-init] ensuring admin user exists..."
superset fab create-admin \
    --username "${SUPERSET_ADMIN_USER:-admin}" \
    --firstname Admin \
    --lastname User \
    --email "${SUPERSET_ADMIN_EMAIL:-admin@example.com}" \
    --password "${SUPERSET_ADMIN_PASSWORD:-admin}" || true

echo "[superset-init] initializing roles and permissions..."
superset init

# StarRocks говорит по MySQL-протоколу; dialect "starrocks://" регистрирует
# официальный пакет starrocks (см. Dockerfile).
STARROCKS_URI="starrocks://alert_reader:alert_reader@movies-starrocks:9030/ugc_analytics"

echo "[superset-init] registering StarRocks database connection..."
# Используем set-database-uri (идемпотентно: создаст или обновит запись по имени).
superset set-database-uri \
    --database_name "starrocks_analytics" \
    --uri "${STARROCKS_URI}" || true

echo "[superset-init] starting webserver on :8088..."
exec /usr/bin/run-server.sh

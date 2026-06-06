#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! nc -z "$SQL_HOST" "$DB_PORT"; do
  sleep 1
done
echo "PostgreSQL is ready"

# Миграции применяет только тот контейнер, который запущен с MIGRATE=1
if [ "$MIGRATE" = "1" ]; then
    echo "Running Alembic migrations..."
    alembic upgrade head
fi

# Команда запуска передаётся через CMD/command в docker-compose
exec "$@"

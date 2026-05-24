#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! nc -z $SQL_HOST $DB_PORT; do
  sleep 1
done
echo "PostgreSQL is ready"

echo "Running Alembic migrations..."
alembic upgrade head

# Создание суперпользователя, если заданы логин и пароль
if [ -n "$AUTH_SUPERUSER_LOGIN" ] && [ -n "$AUTH_SUPERUSER_PASSWORD" ]; then
    echo "Creating superuser..."
    python cli.py create-superuser "$AUTH_SUPERUSER_LOGIN" "$AUTH_SUPERUSER_PASSWORD"
else
    echo "Skipping superuser creation (AUTH_SUPERUSER_LOGIN or AUTH_SUPERUSER_PASSWORD not set)"
fi

echo "Starting FastAPI server..."
exec python run.py
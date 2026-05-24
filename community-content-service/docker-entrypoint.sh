#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
while ! nc -z $SQL_HOST $DB_PORT; do
  sleep 1
done
echo "PostgreSQL is ready"

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting FastAPI server..."
exec python run.py

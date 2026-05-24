#!/bin/bash
set -e

# Проверка, что все необходимые переменные окружения заданы
: "${SQL_HOST:?SQL_HOST not set}"
: "${DB_PORT:?DB_PORT not set}"
: "${POSTGRES_USER:?POSTGRES_USER not set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set}"
: "${POSTGRES_DB:?POSTGRES_DB not set}"

export PGPASSWORD="$POSTGRES_PASSWORD"

echo "Version psql client:"
psql --version

echo "Waiting for database to be ready..."
while ! psql -h "$SQL_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" >/dev/null 2>&1; do
  sleep 1
done

echo "Database is ready!"
psql -h "$SQL_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version();"

# Создание схем
echo "Creating database schemas if not exist..."
psql -h "$SQL_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOF
CREATE SCHEMA IF NOT EXISTS django_admin;
CREATE SCHEMA IF NOT EXISTS content;
EOF

echo "Collect static files..."
python manage.py collectstatic --noinput

echo "Applying migrations..."
python manage.py migrate --noinput

# Загрузка первичных данных, не использую фикстуры джанго потому что COPY гораздо быстрее 
echo "Loading initial data from /opt/database_dump.sql..."
psql -h "$SQL_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /opt/database_dump.sql

echo "Starting uwsgi..."
exec uwsgi --strict --ini uwsgi.ini
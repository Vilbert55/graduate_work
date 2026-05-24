FROM python:3.12.13-slim

WORKDIR /opt/auth-service

# Установка системных зависимостей (для psycopg2 и curl)
RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Poetry
RUN pip install --no-cache-dir poetry==2.3.4
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --without dev --without test

COPY . .

# Делаем entrypoint исполняемым
COPY docker-entrypoint.sh /opt/auth-service/docker-entrypoint.sh
RUN chmod +x /opt/auth-service/docker-entrypoint.sh

EXPOSE 8002

ENTRYPOINT ["/opt/auth-service/docker-entrypoint.sh"]
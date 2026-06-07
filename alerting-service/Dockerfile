FROM python:3.12.13-slim

WORKDIR /opt/alerting-service

# netcat — docker-entrypoint.sh ждёт готовности Postgres через `nc -z`
RUN apt-get update && apt-get install -y \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.4.0
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml ./
RUN poetry install --no-interaction --no-ansi --without dev --no-root

COPY . .

RUN chmod +x /opt/alerting-service/docker-entrypoint.sh

# Запуск от не root пользователя.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /opt/alerting-service
USER appuser

ENTRYPOINT ["/opt/alerting-service/docker-entrypoint.sh"]

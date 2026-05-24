FROM python:3.12.13-slim

WORKDIR /opt/notifications-service

RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.4.0
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --without dev

COPY . .

RUN chmod +x /opt/notifications-service/docker-entrypoint.sh

ENTRYPOINT ["/opt/notifications-service/docker-entrypoint.sh"]

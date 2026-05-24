FROM python:3.12.13-slim

WORKDIR /opt/activity-tracker-service

RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.3.4
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-interaction --no-ansi --without dev

COPY . .

COPY docker-entrypoint.sh /opt/activity-tracker-service/docker-entrypoint.sh
RUN chmod +x /opt/activity-tracker-service/docker-entrypoint.sh

EXPOSE 8003

ENTRYPOINT ["/opt/activity-tracker-service/docker-entrypoint.sh"]

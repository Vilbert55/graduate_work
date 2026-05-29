FROM python:3.12.13-slim

WORKDIR /opt/alerting-service

RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.4.0
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml ./
RUN poetry install --no-interaction --no-ansi --without dev --no-root

COPY . .

RUN chmod +x /opt/alerting-service/docker-entrypoint.sh

ENTRYPOINT ["/opt/alerting-service/docker-entrypoint.sh"]

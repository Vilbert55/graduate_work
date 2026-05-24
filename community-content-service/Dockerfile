FROM python:3.12.13-slim

WORKDIR /opt/community-content-service

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Poetry
RUN pip install --no-cache-dir poetry==2.3.4
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-interaction --no-ansi --without dev

COPY . .

# Делаем entrypoint исполняемым
COPY docker-entrypoint.sh /opt/community-content-service/docker-entrypoint.sh
RUN chmod +x /opt/community-content-service/docker-entrypoint.sh

EXPOSE 8004

ENTRYPOINT ["/opt/community-content-service/docker-entrypoint.sh"]

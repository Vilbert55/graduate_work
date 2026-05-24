FROM python:3.12.13-slim

WORKDIR /opt/films-search-service

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir poetry==2.3.4

# Настройки Poetry
ENV POETRY_VIRTUALENVS_CREATE=false

# Копируем зависимости
COPY pyproject.toml poetry.lock ./

# Устанавливаем зависимости проекта
RUN poetry install --no-interaction --no-ansi  --without dev

# Копируем проект
COPY . .

# Создаем директории для логов
RUN mkdir -p /var/log/fastapi

# Делаем entrypoint исполняемым
COPY docker-entrypoint.sh /opt/films-search-service/docker-entrypoint.sh
RUN chmod +x /opt/films-search-service/docker-entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["/opt/films-search-service/docker-entrypoint.sh"]
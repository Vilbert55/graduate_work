FROM python:3.12.13

WORKDIR /opt/admin-panel-service

# Устанавливаем системные утилиты
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir poetry==2.3.4

# Настройки Poetry
ENV POETRY_VIRTUALENVS_CREATE=false

# Копируем зависимости
COPY pyproject.toml poetry.lock ./

# Устанавливаем зависимости проекта
RUN poetry install --no-interaction --no-ansi --without dev

# Копируем проект
COPY . .

# Создаем директории
RUN mkdir -p /var/www/static /var/www/media

COPY docker-entrypoint.sh /opt/admin-panel-service/docker-entrypoint.sh
COPY database_dump.sql /opt/database_dump.sql
RUN chmod +x /opt/admin-panel-service/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/opt/admin-panel-service/docker-entrypoint.sh"]
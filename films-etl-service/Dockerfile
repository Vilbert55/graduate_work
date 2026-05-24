FROM python:3.12.13-slim

WORKDIR /opt/app

# Устанавливаем системные утилиты
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir poetry==2.3.4

# Настройки Poetry
ENV POETRY_VIRTUALENVS_CREATE=false

# Копируем зависимости
COPY pyproject.toml poetry.lock ./

# Устанавливаем зависимости
RUN poetry install --no-interaction --no-ansi  --without dev

# Копируем исходный код
COPY . .

# Папка для хранения состояния
RUN mkdir -p /opt/app/state

# Делаем entrypoint исполняемым и запускаем
COPY docker-entrypoint.sh /opt/app/docker-entrypoint.sh
RUN chmod +x /opt/app/docker-entrypoint.sh

ENTRYPOINT ["/opt/app/docker-entrypoint.sh"]
CMD ["python", "run.py"]
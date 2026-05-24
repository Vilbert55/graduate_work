# Функциональные тесты для FastAPI

Этот каталог содержит функциональные тесты для сервиса `movies-films-search-service`. Тесты проверяют работу API в изолированном окружении с использованием реальных зависимостей (Redis, Elasticsearch).

## Структура

```
tests/functional/
├── docker-compose.yml       # Docker Compose для тестового окружения
├── Dockerfile.tests         # Dockerfile для контейнера с тестами
├── pyproject.toml           # Зависимости Python (pytest, etc.)
├── .env                     # Переменные окружения для тестов
├── conftest.py              # Pytest фикстуры (общие для всех тестов)
├── src/                     # Директория с тестами
│   └── test_*.py            # Файлы тестов
├── testdata/                # Тестовые данные (JSON, фикстуры)
└── utils/                   # Вспомогательные модули
    ├── __init__.py
    └── settings.py          # Настройки для тестов (чтение .env)
```

## Запуск тестов

### Способ 1: в контейнерах Docker

Поднимается полное тестовое окружение: Redis, Elasticsearch, FastAPI и контейнер с pytest.
Выполняется автоматический запуск всех функциональных тестов.
После завершения тестов все контейнеры автоматически останавливаются.

```bash
# Заполните переменные окружения, скопируйте из шаблона .env.template.docker, при необходимости подставьте свои значения
cp tests/functional/.env.template.docker tests/functional/.env

# Из корня проекта выполните
docker compose -f tests/functional/docker-compose.yml up --abort-on-container-exit --exit-code-from movies-tests-runner
```

- `--abort-on-container-exit` – останавливает все контейнеры, если один из них завершился.
- `--exit-code-from movies-tests-runner` – возвращает код выхода контейнера с тестами (полезно для CI).

### Способ 2: запуск с хоста (для разработки)

Запускаются только зависимости (Redis, Elasticsearch, FastAPI) в фоне, а тесты выполняются локально из вашего виртуального окружения.

1. Поднимите тестовые сервисы:
```bash
# 1. Заполните переменные окружения для docker, скопируйте из шаблона .env.template.docker, при необходимости подставьте свои значения
cp tests/functional/.env.template.docker tests/functional/.env

# 2. Заполните переменные окружения для локального запуска тестов - .env в корне проекта
# Скопируйте из шаблона .env.template.local, при необходимости подставьте свои значения
cp tests/functional/.env.template.local .env

docker compose -f tests/functional/docker-compose.yml up -d movies-redis-test movies-elasticsearch-test movies-films-search-service-test
```

2. Убедитесь, что все сервисы здоровы (можно проверить `docker ps` или логи).

3. Активируйте виртуальное окружение с нужной версией python и зависимостями из `pyproject.toml`:
```bash
cd tests/functional
pyenv local 3.12.13
poetry install --no-root
poetry env activate
cd ../..
pytest -v tests/functional/src/
```

4. Запустите тесты:
```bash
pytest -v src
```

5. После завершения тестов остановите и удалите контейнеры:
```bash
docker compose -f tests/functional/docker-compose.yml down -v
```

## Переменные окружения

Файл `tests/functional/.env` содержит параметры подключения к тестовым сервисам (имена контейнеров, порты) для docker. При запуске через `docker-compose` они подхватываются автоматически. При локальном запусте убедитесь, что в `.env` (в корне проекта) указаны правильные хосты (обычно `localhost` и проброшенные порты).

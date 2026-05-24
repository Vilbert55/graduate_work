# UGC API

Сервис сбора пользовательских событий онлайн-кинотеатра. Принимает события через HTTP и публикует их в Kafka для последующей обработки.

## События

| Эндпоинт | Описание |
|---|---|
| `POST /ugc/api/v1/events/click` | Клик по элементу интерфейса |
| `POST /ugc/api/v1/events/view` | Прогресс просмотра фильма |
| `POST /ugc/api/v1/events/custom` | Произвольное событие |

Все эндпоинты требуют JWT-токен в заголовке `Authorization: Bearer <token>`.

## Документация

Swagger UI доступен по адресу: **http://<хост>/ugc/docs**

## Запуск

Сервис запускается в составе общего `docker-compose.yml` в корне проекта:

```bash
docker compose up -d --build movies-activity-tracker-service
```

Для локального запуска без Docker:

```bash
cd activity-tracker-service
cp ../.env .env          # или задайте переменные вручную
poetry install
poetry run python run.py
```

## Переменные окружения

| Переменная | Описание | Пример |
|---|---|---|
| `AUTH_JWT_SECRET_KEY` | Общий JWT-секрет с auth-service | `supersecret` |
| `UGC_KAFKA_HOST` | Хост брокера Kafka | `movies-kafka` |
| `UGC_KAFKA_PORT` | Порт брокера Kafka | `9092` |
| `UGC_SERVER_PORT` | Порт HTTP-сервера | `8003` |
| `UGC_DEBUG` | Режим отладки Flask | `false` |

## Структура

```
activity-tracker-service/
├── src/
│   ├── api/v1/events.py   # Эндпоинты и Flask-RESTX ресурсы
│   ├── apache_kafka/producer.py  # Публикация событий в Kafka
│   ├── models/events.py   # Pydantic-модели событий
│   ├── core/config.py     # Настройки через pydantic-settings
│   └── main.py            # Фабрика Flask-приложения
└── run.py                 # Точка входа
```

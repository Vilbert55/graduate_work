https://github.com/Vilbert55/notifications_sprint_1
# Онлайн‑кинотеатр — платформа для поиска фильмов с системой авторизации

Проект представляет собой набор микросервисов для онлайн‑кинотеатра.  
Включает ETL‑процесс загрузки данных из PostgreSQL в Elasticsearch, API для поиска фильмов, административную панель и сервис авторизации с управлением ролями.

## Архитектура

- **Admin Panel (Django)** - управление данными (фильмы, жанры, персоны)
- **FastAPI Service** - публичное API для поиска фильмов с кэшированием в Redis
- **ETL Service** - фоновый процесс синхронизации PostgreSQL -> Elasticsearch
- **Auth Service (FastAPI)** - сервис авторизации и ролевой модели (JWT, RBAC)
- **Community Content Service (FastAPI)** - закладки, оценки (0-10) и рецензии пользователей на фильмы
- **Notifications Service** - сервис уведомлений на паттерне Outbox + RabbitMQ. Scheduler создаёт сообщения в БД; publisher атомарно забирает пачки (`SELECT FOR UPDATE SKIP LOCKED`, `pending -> queued`) и публикует в RabbitMQ; email/ws sender-ы перед каждой отправкой проверяют статус сообщения в БД (`SELECT FOR UPDATE`) — защита от дублей при повторной доставке. Гарантия at-least-once; recovery worker возвращает застрявшие сообщения в pending.
- **PostgreSQL** - основное хранилище данных (общая БД для админки и auth)
- **Elasticsearch** - поисковый движок
- **Redis** - кэш для API и хранение хешей refresh‑токенов (вспомогательно)
- **UGC API (Flask)** - сервис сбора пользовательских событий (клики, просмотры, произвольные события) через Kafka
- **Kafka** - брокер сообщений для буферизации событий от UGC API
- **Nginx** - единая точка входа, проксирует запросы к сервисам
- **Jaeger** - сбор трассировок (films-search-service, community-content-service)
- **StarRocks** - аналитическое хранилище для пользовательских событий, поступающих через Kafka
- **Logstash** - обработка и маршрутизация логов из всех сервисов в Elasticsearch
- **Kibana** - визуализация логов из индекса `movies-logs-*`
- **Filebeat** - агент сбора логов Docker-контейнеров, отправляет в Logstash
- **Glitchtip(Sentry)** - мониторинг ошибок (films-search-service, auth-service, community-content-service, activity-tracker-service)
- **Alerting Engine (APScheduler)** _(дипломный)_ — движок SQL-правил поверх StarRocks; по расписанию каждого правила формирует задачи в notifications-service. Управление через SQL-функции `alerting.adm_*` в DBeaver (нет HTTP-API).
- **StarRocks dims + Materialized Views** _(дипломный)_ — `dim_films / dim_users / dim_genres / dim_date` (JDBC Catalog + `SUBMIT TASK SCHEDULE EVERY 1 HOUR`); 5 MV (`mv_user_activity / mv_user_top_genres / mv_segment_film_activity / mv_film_watch_hourly / mv_weekend_film_activity`).
- **Apache Superset** _(дипломный)_ — BI поверх Materialized views StarRocks (datasource `starrocks_analytics`, роль `alert_reader`).
- **Demo tools** _(дипломный, profile `demo`)_ — CLI `seed-users` / `trigger-events` для подготовки демо-сценариев.

## Быстрый запуск

1. Скопируйте `.env.template` в `.env` и при необходимости отредактируйте:
   ```bash
   cp .env.template .env
   ```
2. Запустите все сервисы:
   ```bash
   docker compose up -d --build
   ```
3. После запуска будут доступны:

| Сервис             | URL                            | Описание                          |
|--------------------|--------------------------------|-----------------------------------|
| Admin Panel         | http://localhost/admin/                         | Админка Django                     |
| Films Search API    | http://localhost/films-search/api/v1/films/     | API поиска фильмов                 |
| Swagger (Films)     | http://localhost/films-search/api/docs          | Документация API поиска фильмов    |
| Community Content   | http://localhost/community-content/api/v1/      | API закладок, оценок и рецензий    |
| Swagger (Community) | http://localhost/community-content/api/docs     | Документация Community Content API |
| Auth Service        | http://localhost/auth/                          | Сервис авторизации                 |
| Swagger (Auth)      | http://localhost/auth/docs                      | Документация auth‑сервиса          |
| UGC API             | http://localhost/ugc/api/v1/                    | Сбор пользовательских событий      |
| Swagger (UGC)       | http://localhost/ugc/docs                       | Документация UGC API               |
| Kafka UI            | http://localhost:8080                           | Веб-интерфейс Kafka                |
| Elasticsearch       | http://localhost:9200/                          | Прямой доступ к ES                 |
| Kibana              | http://localhost:5601                           | Визуализация логов (ELK)           |
| Glitchtip (Sentry)  | http://localhost:9000                           | Веб-интерфейс мониторинга ошибок   |
| Jaeger UI           | http://localhost:16686                          | Интерфейс трассировки (Jaeger)     |
| StarRocks HTTP      | http://localhost:8030                           | HTTP‑интерфейс StarRocks           |
| StarRocks MySQL     | localhost:9030                                  | MySQL‑интерфейс StarRocks          |
| RabbitMQ Management | http://localhost:15672                          | Веб-интерфейс RabbitMQ (guest/guest) |
| Mailpit             | http://localhost:8025                           | Локальный SMTP-приёмник для отладки |
| WS Gateway          | ws://localhost:8005/notifications/ws            | WebSocket endpoint для in-app уведомлений |
| Superset            | http://localhost:8088                           | BI поверх Materialized views StarRocks (admin/admin) |


## Структура проекта

```
.
├── admin-panel-service/        # Django‑админка
├── community-content-service   # Сервис пользовательских рецензий, лайков
├── films-search-service/       # API поиска фильмов
├── films-etl-service/          # ETL‑сервис
├── auth-service/               # Сервис авторизации
├── activity-tracker-service/   # UGC API — сбор пользовательских событий
├── alerting-service/           # (дипломный) движок SQL-правил поверх StarRocks
├── starrocks_dims_init/        # (дипломный) init: dim_*, JDBC Catalog, MV, alert_reader
├── superset/                   # (дипломный) Apache Superset BI
├── demo-tools/                 # (дипломный) CLI demo-seeder + event-trigger
├── configs-nginx/              # Конфиги Nginx
├── configs-logstash/           # Pipeline Logstash
├── configs-filebeat/           # Конфиг Filebeat
├── docker-compose.yml
├── .env.template               # шаблон файла переменных окружения (.env)
├── es_schema_movies.json       # Схема индекса фильмов для Elasticsearch
├── diploma_tz.md               # Дипломное ТЗ (расширенное)
├── diploma_tz_short.md         # Дипломное ТЗ (короткое)
├── cheatsheet.md               # (дипломный) личная шпаргалка: как всё устроено end-to-end
├── demo.md                     # (дипломный) сценарий демонстрации (запись видео)
├── .github                     # Workflow Github Actions
└── README.md                   # Этот файл
```

## Технологии

- **Python 3.12**
- **Django 5.2** + **FastAPI** + **Flask** + **Uvicorn**
- **PostgreSQL 16** + **Elasticsearch 8** + **Redis 7** + **Kafka** + **RabbitMQ**
- **Docker** + **Docker Compose**
- **Nginx** (reverse proxy)
- **SQLAlchemy** + **Alembic** (миграции)
- **JWT** (async‑fastapi‑jwt‑auth)
- **ELK** (Elasticsearch + Logstash + Kibana + Filebeat) - централизованное логирование
- **Glitchtip(Sentry)** - мониторинг ошибок
- **Pytest** (тесты)
- **Poetry** (управление зависимостями)

## Централизованное логирование (ELK)

Логи всех Docker-контейнеров автоматически собираются и индексируются:

1. **Filebeat** читает stdout/stderr контейнеров через Docker socket и обогащает записи метаданными контейнера.
2. **Logstash** принимает логи по протоколу Beats (порт 5044), опционально парсит JSON и записывает в Elasticsearch.
3. Логи доступны в **Kibana** -> Management -> Data Views -> создать паттерн `movies-logs-*`.

## Мониторинг ошибок Glitchtip (Sentry)

Интеграция активируется через переменные окружения. При пустом значении — отключена:

```env
FILMS_SEARCH_SENTRY_DSN=http://<ключ>@sentry-api:8000/<id>
AUTH_SENTRY_DSN=http://<ключ>@sentry-api:8000/<id>
COMMUNITY_SENTRY_DSN=http://<ключ>@sentry-api:8000/<id>
UGC_SENTRY_DSN=http://<ключ>@sentry-api:8000/<id>
```

Sentry настроен в сервисах `films-search-service`, `auth-service`, `community-content-service`, `activity-tracker-service`. Автоматически захватывает необработанные исключения FastAPI.

Эндпоинты всегда вызывающие ошибку, для проверки трекинга ошибок:
http://localhost/community-content/api/sentry-debug
http://localhost/auth/sentry-debug
http://localhost/ugc/sentry-debug
http://localhost/films-search/api/sentry-debug

## Аналитическое хранилище (StarRocks)

События, отправленные в Kafka через UGC API, непрерывно загружаются в StarRocks с помощью встроенного механизма Routine Load.

- StarRocks подписывается на топики Kafka (`views`, `clicks`, `custom_events`).
- При старте контейнера `starrocks-init` выполняет `init.sql`, который:
  - создаёт базу данных `ugc_analytics`;
  - создаёт таблицу `user_events` со схемой, подходящей для хранения событий всех типов;
  - настраивает три Routine Load‑задачи — по одной на каждый топик.
- Routine Load обеспечивает устойчивость к сбоям: после восстановления Kafka или StarRocks загрузка автоматически продолжается с последнего зафиксированного смещения.
- Данные доступны для аналитических запросов через MySQL‑интерфейс StarRocks на порту `9030`.


## Примечания

- ETL‑процесс автоматически создаёт индекс в Elasticsearch при первом запуске.
- Данные для БД загружаются из `database_dump.sql` при инициализации контейнера PostgreSQL.
- Все сервисы используют общую сеть `movies-net`.
- Health‑чекеры настроены для автоматического перезапуска сервисов.

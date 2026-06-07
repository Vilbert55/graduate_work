# alerting-service

Event-driven движок, исполняющий SQL-правила аналитика поверх StarRocks и
порождающий задачи в `notifications-service`.

Что делает движок на каждое срабатывание правила (плановое по cron или ручное):
выполняет SQL в StarRocks -> применяет двухуровневый лимит уведомлений -> одной
атомарной транзакцией Postgres пишет историю доставки, создаёт задачу в
`notifications-service` (с per-user контекстом) и финализирует журнал запуска.
Поддерживаются: per-user контекст в шаблоне письма (ФТ-2), frequency cap (ФТ-3),
партиционированная история доставки с retention (ФТ-8), восстановление
прерванных запусков после сбоя (НФТ-3), юнит-тесты бизнес-логики (НФТ-6).

## Архитектура

- **Postgres (схема `alerting` в общей `movies-db`)** — источник истины:
  правила (`t_rules`), история запусков (`t_runs`), история доставки
  (`t_dispatch_history`). Управление — через `adm_*` SQL-функции.
- **StarRocks (`ugc_analytics`)** — аналитическое хранилище. Движок ходит
  туда под ролью `alert_reader` (только SELECT).
- **`notifications-service`** — доставка. Alerting вызывает
  `notifications.adm_create_task(...)` с готовой аудиторией, per-user контекстом
  (`audience.params_by_user`) и идемпотентным ключом `alerting:{rule_id}:{run_id}`.

## Контракт правил

SQL-запрос правила обязан возвращать колонку `user_id` и опционально `context`
(JSON-объект для подстановки в шаблон уведомления). В StarRocks такой JSON удобно
собрать через `to_json(named_struct(...))`: `named_struct` строит структуру
ключ-значение, `to_json` сериализует её в JSON-строку.

```sql
SELECT user_id,
       to_json(named_struct('top_genres', t.top_genres)) AS context
FROM ugc_analytics.mv_user_activity a
JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
WHERE a.was_active_last_month = TRUE
  AND a.last_watch_at < now() - INTERVAL 7 DAY;
```

`context` (JSON-объект) попадает в письмо как per-user параметры шаблона: движок
кладёт его в `audience.params_by_user[user_id]`, а scheduler `notifications`
мерджит поверх общих `params` при рендере Jinja.

## Валидация SQL-правил

Postgres не имеет соединения со StarRocks и не понимает её диалект (`to_json`,
`named_struct`, `INTERVAL ... DAY`), поэтому проверить исполнимость запроса прямо
в `adm_create_rule` нельзя. Контроль многоуровневый:

1. **Статическая проверка формы** в `adm_create_rule` (read-only `SELECT`/`WITH`, один оператор, есть колонка `user_id`; комментарии при проверке игнорируются).
2. **Аналитик заранее проверяет SQL в StarRocks сам** (DBeaver под `alert_reader`) см. `examples.sql`, шаг 1. Это обязательный первый шаг.
3. **`adm_dry_run_rule`** — реальный прогон в StarRocks без рассылки. Правило создаётся выключенным (`is_enabled=FALSE`); включать после успешного dry-run.
4. **Безопасность: роль `alert_reader`** (только `SELECT` на `ugc_analytics`): даже неверный SQL не изменит данные, а упавший запуск виден в `v_runs` (`status='failed'`), письма при этом не уходят.

## SQL-API: соглашение об именовании

Все объекты в схеме `alerting`.

| Префикс | Кто вызывает | Описание |
|---|---|---|
| `adm_*` | роль `alerting_admin` | Управление правилами |
| `v_*`   | роль `alerting_admin` | Мониторинговые представления |
| `t_*`   | — | Таблицы (прямой доступ только у владельца) |

## Функции для администратора

| Функция | Назначение |
|---|---|
| `adm_create_rule(...)` | Создать правило (идемпотентна) |
| `adm_update_rule(...)` | Изменить параметры (NULL = не менять) |
| `adm_enable_rule` / `adm_disable_rule` | Переключатели |
| `adm_delete_rule` | Полное удаление (правило + история) |
| `adm_dry_run_rule` | Тестовый прогон: SQL + размер аудитории до/после лимита, без рассылки |
| `adm_trigger_rule` | Ручной запуск вне расписания |

## Представления

| Представление | Содержимое |
|---|---|
| `v_rules` | Статус правил, расписание, число отправок за 24 ч |
| `v_runs` | История срабатываний |
| `v_dispatch` | История отправок (аудит) |

## Роль alerting_admin

Создание пользователя-администратора (выполнить под `postgres`):

```sql
CREATE USER alerting_admin_ivanov WITH PASSWORD 'strong_password';
GRANT alerting_admin TO alerting_admin_ivanov;
```

Полный набор примеров — `examples.sql`.

## Переменные окружения

Postgres берётся из **общих** переменных проекта (БД `movies` одна на весь
`docker-compose`), всё остальное — под префиксом `ALERTING_`:

| Переменная | Назначение |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Креды общей БД |
| `SQL_HOST` / `DB_PORT` | Хост / порт Postgres |
| `ALERTING_STARROCKS_HOST/PORT/USER/PASSWORD/DB` | Подключение к StarRocks (роль `alert_reader`) |
| `ALERTING_STARROCKS_QUERY_TIMEOUT_SEC` | Тайм-аут SQL-правила (30) |
| `ALERTING_STARROCKS_CONNECT_TIMEOUT_SEC` | Тайм-аут установки соединения (10) |
| `ALERTING_RULES_REFRESH_INTERVAL_SEC` | Период пересинхронизации правил (60) |
| `ALERTING_DISPATCH_RETENTION_DAYS` | Хранение истории отправок, дней (90) |
| `ALERTING_RECOVERY_GRACE_SEC` | Порог «осиротевшего» running-запуска (300) |
| `ALERTING_GLOBAL_PER_USER_PER_DAY` | Общий дневной потолок писем на пользователя (3; 0 — выкл.) |
| `ALERTING_LOG_LEVEL` / `ALERTING_SENTRY_DSN` | Логи / Sentry |

## Структура

```
alerting-service/
├── alembic/
│   ├── env.py
│   └── versions/0001_initial.py    # таблицы + загрузка sql/* (как в notifications)
├── alembic.ini
├── docker-entrypoint.sh            # MIGRATE=1 -> alembic upgrade head; exec $@
├── Dockerfile
├── pyproject.toml
├── README.md
├── examples.sql                    # шпаргалка для аналитика
├── sql/
│   ├── functions/                  # adm_* функции + 007_maint_dispatch_partitions (партиции)
│   ├── views/                      # v_rules, v_runs, v_dispatch
│   ├── roles/                      # alerting_admin
│   └── seed/                       # шаблоны через notifications.adm_upsert_template
├── tests/                          # юнит-тесты бизнес-логики (НФТ-6): pytest
└── src/
    ├── core/config.py              # pydantic-settings, префикс ALERTING_
    ├── db/postgres.py
    ├── db/starrocks.py             # aiomysql-соединение
    ├── models/entity.py            # Rule / Run / DispatchHistory (read-only ORM)
    ├── services/executor.py        # ядро: SQL -> cap -> история -> задача (атомарно)
    └── workers/
        ├── main.py                 # entrypoint (python -m src.workers.main)
        └── engine.py               # APScheduler + recovery + обслуживание партиций
```

## Тесты

Нужен **Poetry ≥ 2.0** (конфиг на PEP 621 `[project]`; на Poetry 1.x команда
падает с ошибкой `'name'`).

```bash
cd alerting-service && poetry install --with dev && poetry run pytest
```

## Запуск

```bash
docker compose up -d \
    movies-db \
    movies-notifications-migrations \
    movies-alerting-migrations \
    movies-starrocks \
    movies-alerting-engine
```

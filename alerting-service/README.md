# alerting-service

Event-driven движок, исполняющий SQL-правила аналитика поверх StarRocks и
порождающий задачи в `notifications-service`.

> Состояние на конец недели 2: каркас. Полная цепочка (выборка из StarRocks,
> лимит уведомлений, идемпотентность, восстановление, партиционирование) — задача недели 3.

## Архитектура

- **Postgres (схема `alerting` в общей `movies-db`)** — источник истины:
  правила (`t_rules`), история запусков (`t_runs`), история доставки
  (`t_dispatch_history`). Управление — через `adm_*` SQL-функции.
- **StarRocks (`ugc_analytics`)** — аналитическое хранилище. Движок ходит
  туда под ролью `alert_reader` (только SELECT).
- **`notifications-service`** — доставка. Alerting вызывает
  `notifications.adm_create_task(...)` с готовой аудиторией и идемпотентным
  ключом (на неделе 3).

## Контракт правил

SQL-запрос правила обязан возвращать колонку `user_id` и опционально `context`
(JSON-объект для подстановки в шаблон уведомления).

```sql
SELECT user_id,
       json_object('top_genres', t.top_genres) AS context
FROM ugc_analytics.mv_user_activity a
JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
WHERE a.was_active_last_month = TRUE
  AND a.last_watch_at < now() - INTERVAL 7 DAY;
```

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
| `adm_delete_rule` | Мягкое удаление |
| `adm_dry_run_rule` | Тестовый прогон (на неделе 2 — заглушка) |
| `adm_trigger_rule` | Ручной запуск (на неделе 2 — NOTIFY без исполнения) |

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

## Структура

```
alerting-service/
├── alembic/
│   ├── env.py
│   └── versions/0001_initial.py    # таблицы + загрузка sql/* (как в notifications)
├── alembic.ini
├── docker-entrypoint.sh            # MIGRATE=1 → alembic upgrade head; exec $@
├── Dockerfile
├── pyproject.toml
├── README.md
├── examples.sql                    # шпаргалка для аналитика
├── sql/
│   ├── functions/                  # adm_* функции
│   ├── views/                      # v_rules, v_runs, v_dispatch
│   ├── roles/                      # alerting_admin
│   └── seed/                       # шаблоны через notifications.adm_upsert_template
└── src/
    ├── core/config.py              # pydantic-settings, префикс ALERTING_
    ├── db/postgres.py
    ├── db/starrocks.py             # aiomysql-пул
    ├── models/entity.py            # Rule / Run / DispatchHistory (read-only ORM)
    └── workers/
        ├── main.py                 # entrypoint (python -m src.workers.main)
        └── engine.py               # APScheduler-движок
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

# Сводка  — неделя 2


## 1. Что это и зачем

Между двумя готовыми конвейерами проекта — `activity-tracker -> Kafka -> StarRocks`
(события) и `notifications-service` (доставка писем) — не хватало звена «данные -> действие».
Новый сервис `alerting-service` его замыкает: продуктовый аналитик пишет SQL-правило
(`SELECT user_id, context FROM mv_*`), регистрирует одной функцией, а движок по расписанию
выполняет запрос в StarRocks и создаёт задачу в notifications. Никакого маркетолога-оператора
в цикле — отсюда часы вместо дней на запуск рассылки.

**Ключевое отличие от Mindbox/Customer.io/Braze:** целевой пользователь — аналитик с SQL,
поэтому интерфейс управления — SQL-функции в Postgres, а не визуальный конструктор.

---

## 2. Что сделано к концу недели 2

Минимальный, но **сквозной** end-to-end:

```
seed-users -> trigger-events -> Kafka -> Routine Load -> user_events (StarRocks)
  -> mv_* (async MV) -> adm_create_rule (Postgres) -> adm_trigger_rule
  -> pg_notify -> alerting-engine -> SQL в StarRocks под alert_reader
  -> notifications.adm_create_task -> RabbitMQ -> email-sender -> Mailpit (22 письма)
```
Параллельно поднят Superset поверх тех же Materialized views.

---

## 3. Карта кода — где что смотреть

### Главный артефакт — `alerting-service/`
| Путь | Что |
|---|---|
| `src/workers/engine.py` | Ядро движка: APScheduler (cron каждого правила) + LISTEN на канале `alerting_trigger` (ручной запуск/dry-run). Синхронизация jobs с `t_rules`. |
| `src/services/executor.py` | Исполнение одного срабатывания: SQL в StarRocks -> парсинг `user_id` -> `adm_create_task` с идемпотентным ключом -> запись `t_runs`. **Докстринг наверху честно перечисляет упрощения недели 2.** |
| `src/db/starrocks.py` | Короткоживущее соединение под `alert_reader` (MySQL-протокол, aiomysql). |
| `src/db/postgres.py`, `src/models/entity.py` | SQLAlchemy: движок читает `t_rules` через ORM; пишет в `t_runs` через raw SQL. |
| `src/core/config.py` | Pydantic-settings, префикс `ALERTING_`. |
| `sql/functions/000_helpers.sql` | Внутренние хелперы: `_check_channel`, `_check_cron` (валидация), `_enqueue_rule_run` (общее тело trigger/dry-run). |
| `sql/functions/001..006` | Публичный SQL-API аналитика: `adm_create/update/enable/disable/delete/dry_run/trigger_rule`. |
| `sql/views/` | `v_rules` / `v_runs` / `v_dispatch` — аудит для аналитика. |
| `sql/roles/`, `sql/seed/` | Роль `alerting_admin`; шаблоны писем (через `notifications.adm_upsert_template`). |
| `alembic/versions/0001_initial.py` | Вся схема `alerting` + загрузка `sql/*` в одной миграции. |
| `examples.sql` | Шпаргалка аналитика — готовые вызовы для DBeaver. |

### StarRocks (аналитический слой)
| Путь | Что |
|---|---|
| `starrocks_init/init.sql` | `user_events` (переведена в **Primary Key table** для дедупликации), 4 Routine Load из Kafka. |
| `starrocks_dims_init/init.sql` | JDBC Catalog на Postgres, `dim_*`, `SUBMIT TASK ... SCHEDULE EVERY 1 HOUR`, 5 Materialized views, роль `alert_reader` (GRANT SELECT на таблицы **и MV**). |

### Демо и BI
| Путь | Что |
|---|---|
| `demo-tools/src/` | Typer-CLI: `seed-users` (демо-юзеры) + `trigger-events` (3 сценария событий). Профиль `demo`. |
| `superset/` | Apache Superset 6.1.0, датасорс StarRocks (`starrocks+pymysql://`). |

### Интеграционные правки в чужих сервисах (не ломая их API)
| Сервис | Что добавлено |
|---|---|
| `auth-service` | Миграция: nullable `gender/age/country/is_demo` в `auth.users` (под сегментацию `dim_users`). |
| `activity-tracker-service` | `event_type=recommendation` (`POST /ugc/api/v1/events/recommendation`) + Kafka-топик `recommendations` — замыкает контур «письмо -> клик -> факт». |

---

## 4. Три архитектурных решения (на вопросы «почему так»)

1. **Управление — SQL-функции, не REST.** Целевой юзер живёт в DBeaver. `SELECT adm_create_rule(...)` естественнее `curl`. REST вынесен в «возможные улучшения» (тонкая обёртка над теми же функциями).
2. **Синхронизация `dim_*` — StarRocks JDBC Catalog + `SUBMIT TASK`, а не отдельный Python-ETL.** Та же логика «оркестрация внутри StarRocks», что у Routine Load для Kafka. Минус сервис, плюс честный DWH-нарратив. Отдельный воркер оправдан при CDC — здесь полная перезаливка 3 таблиц раз в час, избыточно.
3. **Идемпотентность — ключ `alerting:{rule_id}:{run_id}` в `adm_create_task`.** Повтор после сбоя между «посчитали аудиторию» и «создали задачу» не даёт дублей писем.

---

## 5. Что сознательно отложено на неделю 3 (и почему это ок)

Честно зафиксировано в docstring `executor.py` и в плане `diploma_tz_short.md`:

| Отложено | Требование | Текущее состояние |
|---|---|---|
| Per-user `context` из SQL в письмо | ФТ-2 | SQL возвращает `context`, но executor читает только `user_id`; `adm_create_task` принимает один `params` на всю аудиторию -> жанры в письме пока по дефолту шаблона. Нужен per-user разлив params. |
| Двухуровневый frequency_cap | ФТ-3 | не применяется, `after_cap = matched`. |
| Построчная запись `t_dispatch_history` + партиции/retention | ФТ-8, §12 | пишется только агрегат в `t_runs`. |
| Recovery прерванных `running`-запусков | НФТ-3 | run «зависнет» в `running` при рестарте между NOTIFY и execute. |
| Юнит-тесты (cap, контракт колонок, ошибки SQL) | НФТ-6 | пока только ручной e2e. |

> Важный нюанс для обсуждения: «опционально `context`» в ФТ-2 — про *наличие* колонки;
> если она есть, подстановка обязана работать. Сейчас это **разрыв с ФТ-2**, закрываем на неделе 3.

---

## 6. Чем демонстрировать

Пошаговый сценарий с командами/запросами — файл **`demo.md`** (полная демонстрация
недель 2–3: терминал -> DBeaver -> Mailpit -> Superset, опционально Postman для замыкания контура).
Готовые SQL-вызовы — `alerting-service/examples.sql`.

---

## 7. Возможные вопросы наставника — заготовки

- **«Почему движок один экземпляр?»** — осознанный MVP-компромисс (R6). Защита: автоперезапуск контейнера + recovery (неделя 3). Масштаб — leader election через `pg_advisory_lock` (вынесено в «улучшения», без внешних координаторов).
- **«Что если аналитик вернёт миллион user_id?»** — потолок `max_users` (усечение + warning), тайм-аут SQL 30 сек на сессию StarRocks (R4, R7).
- **«Почему StarRocks, а не ClickHouse?»** — он уже в проекте под UGC; нужны были Routine Load (Kafka), async MV и JDBC Catalog — всё нативно.
- **«StarRocks 4.0.8 — почему не свежее?»** — на нём весь стек проверен end-to-end; вскрылись и починены версионные особенности (напр. `json_object` не берёт ARRAY -> `to_json(named_struct(...))`; `EXECUTE TASK` не поддерживается -> прямой `INSERT OVERWRITE` + `REFRESH ... WITH SYNC MODE`).
- **«Как считается ROI правила?»** — через замкнутый контур: реакция на письмо (`recommendation` event) возвращается в `user_events`, аналитик строит конверсию в Superset.

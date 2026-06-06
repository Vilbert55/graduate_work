# Шпаргалка по дипломной части (alerting-service)

Личная памятка: как всё устроено end-to-end, какая функция что вызывает, где что
лежит. Дипломная часть — это **closed-loop alerting**: аналитик пишет SQL-правило
поверх StarRocks, движок по расписанию выполняет его и через `notifications-service`
шлёт письма. Управление — SQL-функциями в Postgres (DBeaver), без HTTP-API.

---

## 1. Одним абзацем

Между двумя уже готовыми частями платформы — потоком событий
(`activity-tracker -> Kafka -> StarRocks`) и доставкой писем
(`notifications-service`) — не хватало звена «данные -> действие». Его закрывает
`alerting-service`: аналитик регистрирует правило (`SELECT user_id, context FROM mv_*`),
а движок по cron каждого правила выполняет запрос в StarRocks, применяет лимиты,
пишет историю и создаёт задачу на рассылку. Маркетолог-оператор из цикла убран —
отсюда часы вместо дней на запуск рассылки.

---

## 2. Карта всей платформы (где что и где Elasticsearch)

| Компонент | Роль | Отношение к диплому |
|---|---|---|
| **admin-panel (Django)** | Управление фильмами/жанрами/персонами в Postgres `content` | Источник для `dim_films/dim_genres/dim_date` |
| **films-etl-service** | ETL `Postgres content -> Elasticsearch` | — (не диплом) |
| **films-search-service (FastAPI)** | Поиск фильмов поверх **Elasticsearch** | — |
| **auth-service (FastAPI)** | Пользователи, JWT, RBAC. Добавлены поля `gender/age/country/is_demo` | Источник для `dim_users` (сегментация) |
| **activity-tracker (Flask, UGC)** | Приём событий (`view/click/custom/recommendation`) -> Kafka. Публичный `GET /ugc/email/click` (`track.py`) ловит клик по ссылке из письма | Старт контура (события) **и** замыкание (клик из письма -> recommendation) |
| **Kafka** | Буфер событий (топики `views/clicks/custom_events/recommendations`) | StarRocks читает их Routine Load |
| **StarRocks** | Аналитическое хранилище: `user_events`, `dim_*`, `mv_*` | **Ядро аналитики диплома** |
| **notifications-service** | Доставка: Scheduler -> Outbox -> RabbitMQ -> email/ws sender -> Mailpit | Конец контура: alerting зовёт `adm_create_task` |
| **alerting-service (APScheduler)** | **Движок SQL-правил** (диплом) | Главный артефакт |
| **Superset** | BI поверх `mv_*` StarRocks | Диплом (ФТ-11) |
| **demo-tools (CLI)** | `seed-users` / `trigger-events` для демо | Подготовка демо-данных (юзеры + события) |
| **Elasticsearch** | (1) поисковый индекс фильмов; (2) хранилище логов ELK | Диплома **не касается** напрямую |

**Про Elasticsearch отдельно** (чтобы не путаться): в платформе ES играет две
независимые роли, и **ни одна не связана с alerting**:
1. **Поиск фильмов.** `films-etl-service` льёт данные из Postgres `content` в
   индекс ES; `films-search-service` ищет по нему. Дипломная аналитика идёт через
   StarRocks, а не ES — это разные хранилища под разные задачи (поиск vs OLAP).
2. **Логи (ELK).** `Filebeat -> Logstash -> Elasticsearch -> Kibana` собирает
   stdout всех контейнеров в индекс `movies-logs-*`. Туда же попадают и
   JSON-логи alerting-движка — это единственная точка, где диплом «виден» в ES,
   и то лишь как строки логов.

Вывод для защиты: **аналитический слой диплома — StarRocks, а не Elasticsearch.**

---

## 3. Главный контур (end-to-end)

```
seed-users -> trigger-events -> Kafka -> Routine Load -> user_events (StarRocks)
   -> REFRESH mv_*                         (аналитический слой)
   -> adm_create_rule (Postgres)           (аналитик регистрирует правило)
   -> adm_trigger_rule / cron-тик          (запуск правила)
   -> alerting-engine: SQL в StarRocks под alert_reader   (выборка аудитории)
   -> frequency cap -> t_dispatch_history  (лимиты + история, одна транзакция)
   -> notifications.adm_create_task (per-user context)    (задача на рассылку)
   -> RabbitMQ -> email-sender -> Mailpit  (письма со ссылкой «Открыть подборку»)
   -> клик по ссылке -> GET /ugc/email/click (activity-tracker) -> recommendation-событие -> Kafka -> user_events
   -> dispatch_log + mv_rule_conversion -> воронка «отправили -> перешли по ссылке» в Superset
```

Последние строки — замыкание петли: в письме персональная ссылка
`http://localhost/ugc/email/click?rule=<код>&user=<uuid>&run=<id>`; клик дёргает
публичный эндпоинт `activity-tracker-service/src/api/v1/track.py`, тот шлёт событие
`recommendation` (`action=clicked`) в Kafka -> оно возвращается в `user_events`.
Журнал отправок копируется в StarRocks (`dispatch_log`), и `mv_rule_conversion`
показывает, сколько людей реально перешли по ссылке. Идемпотентность: `request_id`
= `uuid5(rule, run, user)` — повтор клика по той же ссылке дубля не создаёт, а новое
срабатывание правила (новый `run`) даёт новую ссылку (отдельный переход).

---

## 4. Граф вызовов движка (кто кого зовёт)

Точка входа: `python -m src.workers.main` -> `engine.run()`.

```
engine.run()                              (src/workers/engine.py)
├─ AsyncIOScheduler(timezone=UTC).start()
├─ _maintain_partitions()                 один раз + cron «5 0 * * *» (раз в сутки)
│    └─ SQL: alerting.maint_dispatch_partitions(retention_days)
├─ _recover_interrupted_runs()            дозавершить «running» после сбоя
│    └─ execute_rule(rule_id, run_id=...) для каждого зависшего запуска
├─ _sync_jobs(scheduler)                  первичная загрузка правил в планировщик
│    └─ на каждое активное правило: scheduler.add_job(_tick, cron)
├─ asyncio.create_task(_listen_for_triggers(stop_event))   фоновый LISTEN
└─ loop: каждые rules_refresh_interval_sec -> _sync_jobs()  (подхватить вкл/выкл)

_tick(rule_id, rule_code)                 вызывается APScheduler по cron правила
└─ execute_rule(rule_id)                  run_id=None -> создаём новый запуск

_listen_for_triggers(stop_event)          asyncpg LISTEN канала 'alerting_trigger'
└─ _on_notify -> _handle_trigger_payload(payload)
     payload = 'trigger|dryrun:{rule_id}:{run_id}'
     └─ execute_rule(rule_id, run_id=run_id, dry_run=(kind=='dryrun'))
```

Ядро исполнения: `execute_rule(...)` (`src/services/executor.py`), три фазы:

```
execute_rule(rule_id, run_id=None, dry_run=False)
│
├─ Фаза 1 (своя транзакция, сразу commit):
│    _load_rule()        прочитать правило (или RuleNotFoundError)
│    _create_run() | _update_run(status='running')   пометить запуск running
│
├─ Фаза 2 (вне транзакции Postgres):
│    _fetch_audience(sql_query)
│      └─ starrocks_connection()  (aiomysql, под alert_reader, с тайм-аутом)
│      └─ _extract_audience(rows)  обязательна колонка user_id, дедуп
│           └─ _parse_context(value)   JSON-строка -> dict (per-user context)
│
└─ Фаза 3 (ОДНА транзакция: либо всё, либо ничего):
     FrequencyCap.build(rule.frequency_cap, settings.global_per_user_per_day)
     _blocked_by_cap(session, rule_id, cap, audience)   кого нельзя слать
     _filter_by_cap(audience, blocked)                  оставшиеся
     [обрезка по max_users + warning]
     если есть кому слать и не dry_run:
        _insert_dispatch_history()      строки в недельную партицию
        _create_notification_task()     SELECT notifications.adm_create_task(...)
     _update_run(status='success', счётчики, task_id)
     UPDATE t_rules.last_run_at
   (любое исключение -> rollback -> _finalize_failed() отдельной транзакцией)
```

SQL-сторона запуска (`sql/functions/`):

```
adm_trigger_rule(code)  -> _rule_id(code) -> _enqueue_rule_run(rule_id,'trigger')
adm_dry_run_rule(code)  -> _rule_id(code) -> _enqueue_rule_run(rule_id,'dryrun')
_enqueue_rule_run(rule_id, kind):
   INSERT t_runs(status='running', is_dry_run = kind='dryrun') RETURNING run_id
   pg_notify('alerting_trigger', kind || ':' || rule_id || ':' || run_id)
   -- движок слушает этот канал в _listen_for_triggers
```

---

## 5. SQL-API правил (что вызывает аналитик в DBeaver)

Все под ролью `alerting_admin`. Файлы — `alerting-service/sql/functions/`.

| Функция | Что делает | Валидация |
|---|---|---|
| `adm_create_rule(...)` | Создать правило (идемпотентна по `p_idempotency_key`) | `_check_rule_sql`, `_check_channel`, `_check_cron`, `_check_frequency_cap`, `max_users>0`, шаблон существует |
| `adm_update_rule(...)` | Изменить (NULL-аргумент = не менять) | те же проверки на непустые поля |
| `adm_enable_rule` / `adm_disable_rule` | Вкл/выкл (движок подхватит на `_sync_jobs`) | — |
| `adm_delete_rule` | Мягкое удаление (`is_deleted=TRUE`) | — |
| `adm_dry_run_rule` | Тестовый прогон: SQL + размер аудитории до/после лимита, **без рассылки** | — |
| `adm_trigger_rule` | Ручной запуск вне расписания | — |

Мониторинг (вьюхи): `v_rules` (каталог + отправки за 24ч), `v_runs` (история
запусков), `v_dispatch` (журнал отправок). Готовые вызовы — `examples.sql`.

**Контракт SQL правила:** обязан вернуть колонку `user_id`, опционально `context`
(JSON-объект). `context` собирают через `to_json(named_struct('k', v, ...))`:
`named_struct` строит структуру ключ-значение, `to_json` сериализует её в строку.

---

## 6. StarRocks: откуда берутся данные правил

Файлы: `starrocks_init/init.sql` (события) и `starrocks_dims_init/init.sql`
(измерения, MV, роль).

- **`user_events`** — PK-таблица `(request_id, event_type)`. Дедупликация встроена
  (REPLACE при конфликте PK), поэтому правила свободно считают `count(DISTINCT user_id)`.
  Наполняется **Routine Load** из Kafka: 4 задания (`views/clicks/custom/recommendations`),
  каждое читает свой топик. НЕ партиционирована — обычная HASH-раздача по бакетам.
- **`dim_films / dim_users / dim_genres / dim_date`** — PK-таблицы, наполняются из
  Postgres через **JDBC Catalog** `pg_catalog` (внешний каталог: StarRocks читает
  Postgres как свои таблицы) командой `INSERT OVERWRITE`. Регулярность — нативный
  `SUBMIT TASK ... SCHEDULE EVERY 1 HOUR` внутри StarRocks (отдельного Python-ETL нет).
- **`dispatch_log`** — DUPLICATE KEY-таблица, копия `alerting.t_dispatch_history`
  (журнал отправок) тем же JDBC-механизмом, что и `dim_*` (джойн с `t_rules` ради
  `rule_code`). Нужна, чтобы посчитать отклик: «сколько отправили» живёт в Postgres,
  а Superset/правила ходят только в StarRocks. `SUBMIT TASK sync_dispatch_log`.
- **`mv_*`** — 6 materialized views (`mv_user_activity`, `mv_user_top_genres`,
  `mv_segment_film_activity`, `mv_film_watch_hourly`, `mv_weekend_film_activity`,
  `mv_rule_conversion`), `REFRESH ASYNC` — StarRocks сам пересчитывает их при
  изменении источников. `mv_rule_conversion` = воронка (dispatch_log LEFT JOIN
  переходы `event_type=recommendation, action=clicked`): отправили -> перешли по
  ссылке, по каждому правилу.
- **`alert_reader`** — роль/пользователь только на `SELECT` (на таблицы **и** MV).
  Под ней ходит движок. Это защита: правило аналитика физически не может ничего
  изменить в StarRocks.

Почему **в демо** обновляем измерения вручную: `SUBMIT TASK` идёт раз в час, ждать
нельзя. StarRocks 4.0.8 **не поддерживает** `EXECUTE TASK <имя>`, поэтому повторяем
тот же `INSERT OVERWRITE` + `REFRESH MATERIALIZED VIEW ... WITH SYNC MODE`
(готовый блок — `examples.sql` §7, `demo_full.md` §3).

---

## 7. Frequency cap — два уровня (ФТ-3)

Чистая логика в `executor.py`, запросы к истории — там же в `_blocked_by_cap`.

| Уровень | Откуда значение | Что ограничивает | SQL-условие |
|---|---|---|---|
| `per_rule_per_user_days` | из правила (`frequency_cap`) | не слать одному юзеру это правило чаще раза в N дней | по `rule_id` + `sent_at > now - N дней` |
| `per_user_per_day` | **глобальная настройка движка** `ALERTING_GLOBAL_PER_USER_PER_DAY` | общий потолок писем на юзера в сутки по ВСЕМ правилам | без `rule_id`, `sent_at >= начало суток`, `count >= M` |

**Важный нюанс (почему глобальный потолок — настройка, а не поле правила):**
«общий потолок» по смыслу один на весь сервис (ФТ-3/R8 — защита от перекрытия
правил). Если бы он лежал в каждом правиле, при правилах с разными значениями
(1 и 3) фактический потолок «плавал» бы в зависимости от того, какое правило сейчас
сработало. Поэтому он вынесен в одну настройку движка; в `frequency_cap` правила
допустим только `per_rule_per_user_days` (это проверяет `_check_frequency_cap`).

`FrequencyCap` (frozen dataclass) собирает оба уровня: `per_rule_per_user_days` из
JSONB правила, `per_user_per_day` из настройки. `is_empty` -> лимитов нет ->
`_blocked_by_cap` сразу возвращает пустое множество.

---

## 8. Атомарность, идемпотентность, recovery (НФТ-3)

Схемы `alerting` и `notifications` — в одной БД `movies`, движок ходит под
`postgres`. Поэтому шаги «cap -> история -> `adm_create_task` -> финализация
запуска» сведены в **одну транзакцию** (фаза 3 в `execute_rule`).

- **Идемпотентность/recovery:** пока запуск в статусе `running`, по нему ничего не
  закоммичено. При сбое движок на старте (`_recover_interrupted_runs`) берёт
  `running`-запуски старше `recovery_grace_sec` и повторяет `execute_rule` с тем же
  `run_id` — дублей нет.
- **Вторая страховка:** ключ `alerting:{rule_id}:{run_id}` в `adm_create_task`.
  Даже двойное восстановление вернёт ту же задачу, второго письма не будет.
- **dry-run не «дошлётся»:** `t_runs.is_dry_run=TRUE`; recovery берёт только боевые
  запуски.
- Выборка из StarRocks — ДО транзакции, чтобы внешний запрос не держал блокировку.

---

## 9. Партиционирование истории доставки (это Postgres, не StarRocks!)

`t_dispatch_history` (журнал отправок и основа cap) **в Postgres** нарезана по
неделям. Где это задаётся и как обслуживается:

- **Где задаётся «по неделям»:** в миграции `alembic/versions/0001_initial.py` —
  таблица создаётся как `... PARTITION BY RANGE (sent_at)` (raw DDL, т.к.
  `op.create_table` не умеет PARTITION BY).
- **Где нарезаются сами партиции:** функция `alerting.maint_dispatch_partitions(N)`
  (`sql/functions/007_*`). Она: (1) гарантирует партиции на текущую и следующую
  неделю (`date_trunc('week', now())`, шаг 7 дней; имя `t_dispatch_history_pYYYYMMDD`
  по понедельнику ISO-недели); (2) дропает партиции, чей конец недели старше
  `now - retention`.
- **Как обслуживается:** движок зовёт её при старте и затем по cron «5 0 * * *»
  (раз в сутки), retention из `ALERTING_DISPATCH_RETENTION_DAYS` (90). Первая
  нарезка — прямо в миграции (`SELECT alerting.maint_dispatch_partitions(90)`).

> NB для защиты: автонарезка по неделям — на стороне **Postgres** (`t_dispatch_history`).
> В StarRocks `user_events` партиционирования нет (PK + HASH). Не перепутать.

---

## 10. Валидация правил (ФТ-1, НФТ-2)

- **`p_sql`** — статические проверки в `_check_rule_sql` (`000_helpers.sql`):
  запрос на чтение (`^SELECT|WITH`), один оператор (нет `;` кроме хвоста), есть
  `user_id`. Полноценный EXPLAIN в Postgres-функции невозможен — между Postgres и
  StarRocks нет соединения. Реальную проверку (что запрос исполним в StarRocks)
  делает **`adm_dry_run_rule`** — движок реально выполняет SQL под `alert_reader`.
- **`p_frequency_cap`** — `_check_frequency_cap`: это JSON-объект, единственный
  допустимый ключ `per_rule_per_user_days` (целое > 0). `per_user_per_day` явно
  отвергается с подсказкой про глобальную настройку.
- **`p_channel`** (`email|ws`), **`p_cron`** (5 полей), **`p_template_code`**
  (существует и активен в `notifications.t_templates`), **`p_max_users`** (> 0).
- Колонки `t_rules.status='invalid'` и `last_validation_error` заведены в схеме и
  показаны во `v_rules`, но кодом сейчас не наполняются (задел; решено не делать
  EXPLAIN-on-enable).

---

## 11. Как письмо получает per-user данные (ФТ-2, через notifications)

1. SQL правила вернул `context` (JSON) на каждого юзера.
2. `_create_notification_task` кладёт их в `audience.params_by_user[user_id]` и
   зовёт `notifications.adm_create_task`.
3. Scheduler notifications (`notifications-service/src/workers/scheduler.py`,
   `_bulk_insert_messages`) при рендере шаблона **мерджит**
   `params_by_user[user_id]` поверх общих `task.params` -> у каждого письма свои
   подстановки (например, свои top-3 жанра). Для обычных задач ключа нет —
   поведение не меняется (обратносовместимо, ФТ-12).
4. Шаблон (`sql/seed/001_alerting_templates.sql`) использует `params.top_genres`
   и т.п., с `default(...)` на случай отсутствия.

---

## 12. Карта требований ТЗ -> код (для себя и ревьюера)

| Требование | Где реализовано |
|---|---|
| ФТ-1 создание правила одной функцией + валидация | `adm_create_rule` + `_check_*` хелперы |
| ФТ-2 per-user context в письмо | `executor._create_notification_task` + `notifications/scheduler._bulk_insert_messages` |
| ФТ-3 двухуровневый cap | `executor.FrequencyCap` + `_blocked_by_cap`; глобальный уровень — `ALERTING_GLOBAL_PER_USER_PER_DAY` |
| ФТ-5 dry-run | `adm_dry_run_rule` -> `execute_rule(dry_run=True)` |
| ФТ-6/7 ручной запуск, журнал | `adm_trigger_rule`, `t_runs` / `v_runs` |
| ФТ-8 история доставки + партиции/retention | `t_dispatch_history` + `maint_dispatch_partitions` |
| ФТ-10 синхронизация dim_* средствами StarRocks | `starrocks_dims_init` JDBC Catalog + `SUBMIT TASK` |
| ФТ-11 BI-дашборды | Superset поверх `mv_*`; главный чарт — воронка «отправили -> перешли по ссылке» (`mv_rule_conversion`) |
| Замыкание петли | ссылка в письме (`001_alerting_templates.sql`) -> клик -> `GET /ugc/email/click` (`track.py`, идемпотентно по uuid5 rule+user) -> recommendation -> `dispatch_log` + `mv_rule_conversion` |
| ФТ-12 notifications не ломаем | только `adm_create_task`/`adm_upsert_template` + опциональный `params_by_user` |
| НФТ-3 надёжность/recovery | атомарная фаза 3 + `_recover_interrupted_runs` + идемпотентный ключ |
| НФТ-6 юнит-тесты | `tests/test_executor_logic.py` (контракт колонок, context, cap) |
| R4 миллион user_id | `max_users` (обрезка + warning) + тайм-аут SQL |
| R7 «тяжёлый SQL» | тайм-аут `ALERTING_STARROCKS_QUERY_TIMEOUT_SEC=30` + статическая валидация |
| R8 перекрытие правил | глобальный `per_user_per_day` |

---

## 13. Гочи (на чём спотыкался)

- **StarRocks 4.0.8 не поддерживает `EXECUTE TASK <имя>`** — для ручного обновления
  dim повторяем `INSERT OVERWRITE` из `SUBMIT TASK`, затем `REFRESH ... WITH SYNC MODE`.
- **`json_object` в StarRocks не берёт ARRAY** -> используем `to_json(named_struct(...))`.
- **Диск StarRocks:** при заполнении `> storage_high_watermark_usage_percent` (95%)
  BE отказывает в `CREATE TABLE`. Лечится освобождением диска или временно:
  `ADMIN SET FRONTEND CONFIG ('storage_high_watermark_usage_percent'='99')`.
- **JDBC-драйвер Postgres** StarRocks качает по HTTPS (`driver_url`) при первом
  обращении к `pg_catalog`. Нет интернета/прокси в контейнере -> JDBC Catalog упадёт.
- **Порядок миграций:** `movies-alerting-migrations` зависит от
  `movies-notifications-migrations` (шаблоны через `notifications.adm_upsert_template`).
  Ручной up в обход `depends_on` ломает порядок.
- **ruff не запинен** (latest + preview) — периодически валит CI новыми правилами.
  Конфиги: корневой `ruff.toml` + по одному в некоторых сервисах (nearest-config-wins);
  `tests/` и `alembic/` из линта исключены.

---

## 14. Быстрые проверки (что всё поднялось)

```bash
# Все init/migrations завершились с кодом 0
docker compose ps -a --format '{{.Name}}\t{{.Status}}' \
  | grep -E '(init|migrations)' | grep -v 'Exited (0)' \
  && echo "ВНИМАНИЕ: что-то упало" || echo "OK"

# Движок: планировщик + слушатель + обслуживание партиций
docker compose logs movies-alerting-engine | grep -E 'started|maint|listening'

# StarRocks: каталоги, dim'ы, MV, PK user_events, 4 Routine Load
docker exec movies-starrocks mysql -h127.0.0.1 -P9030 -uroot -e "
  USE ugc_analytics;
  SHOW CATALOGS;                      -- есть pg_catalog
  SELECT count(*) FROM dim_films;     -- ~999
  SELECT count(*) FROM dim_date;      -- ~91051
  SHOW MATERIALIZED VIEWS;            -- 6 mv_*
  DESCRIBE user_events;               -- PRIMARY KEY(request_id, event_type)
  SHOW ROUTINE LOAD\G                 -- 4 загрузчика, состояние RUNNING"

# Postgres: функции alerting и шаблоны
docker exec movies-db psql -U postgres -d movies -c "\df alerting.adm_*"

# Юнит-тесты движка
cd alerting-service && poetry run pytest -q
```

Доступы и пошаговый сценарий показа — `demo_full.md` (рядом). Готовые SQL — `examples.sql`.

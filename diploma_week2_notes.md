# Дипломный проект — аналитическая записка по неделе 2

**Период:** 2026-05-25 → 2026-05-31. Сегодня — 2026-05-29.

Записка фиксирует, что именно сделано на 2-й неделе, какие компромиссы
приняты и что осознанно отложено на 3-ю неделю.

---

## 1. Реализовано на неделе 2

| Блок | Результат |
|---|---|
| **auth-service** | Alembic-миграция `a3c1d9f8b2e0`: nullable `gender / age_group / country` + `is_demo BOOLEAN DEFAULT FALSE` в `auth.users`. Pydantic-схемы регистрации/профиля расширены этими полями (кроме `is_demo` — он не принимается извне). |
| **activity-tracker-service** | Новый эндпоинт `POST /ugc/api/v1/events/recommendation` + Kafka-топик `recommendations`. Замыкает контур «правило → письмо → клик → факт обратно в StarRocks». |
| **starrocks_init/init.sql** | `user_events` переведена в **Primary Key table** по `(request_id, event_type)`. Дедупликация теперь обеспечивается транспортом (REPLACE-семантика StarRocks), а не запросами в правилах. Добавлен Routine Load `recommendations_load`. |
| **starrocks_dims_init/** | Новый init-контейнер: JDBC Catalog `pg_catalog` поверх Postgres, 4 dim-таблицы (включая `dim_date`), 5 Materialized views (включая `mv_weekend_film_activity`), роль и пользователь `alert_reader`. |
| **alerting-service/** | Новый сервис: схема `alerting` (`t_rules` / `t_runs` / `t_dispatch_history`), 7 SQL-функций `adm_*`, 3 представления `v_*`, роль `alerting_admin`, сидинг 3 шаблонов уведомлений через `notifications.adm_upsert_template`. Каркас движка APScheduler работает: читает `t_rules`, ставит cron-jobs на каждое активное правило, на тике структурированно логирует факт срабатывания. |
| **demo-tools/** | Typer-CLI с двумя подкомандами: `seed-users` (идемпотентен по `is_demo=TRUE`) и `trigger-events` (3 сценария: winback / segment_trend / weekend_burst). Profile `demo` — не стартует автоматически. |
| **superset/** | Apache Superset 6.1.0 (актуальный релиз 2026-05-13). Регистрирует StarRocks как datasource `starrocks_analytics` под `alert_reader`. Три готовых SQL для SQL Lab в `superset/README.md`. |
| **`.env.template` / корневой `README.md` / ТЗ** | Обновлены — см. ниже §6. |

---

## 2. Явно отложено на неделю 3

| Что | Почему откладываем |
|---|---|
| Реальная выборка из StarRocks в `_tick` движка | Требует устойчивого исполнения SQL-правила, тайм-аута, потолка выборки, парсинга колонок `user_id` / `context`. Эти куски объёмные и тесно связаны с лимитом уведомлений — лучше делать одним блоком. |
| `adm_dry_run_rule` — реальная логика | Тот же движок. Сейчас функция возвращает заглушку `(0, 0, {})` с правильным контрактом, чтобы аналитик мог писать вызовы уже сейчас. |
| `adm_trigger_rule` — реальное исполнение | На неделе 2 шлёт `pg_notify('alerting_trigger', ...)`, но движок ещё не подписан. На неделе 3 — `LISTEN/NOTIFY` цикл в движке. |
| Лимит уведомлений (`frequency_cap` из `t_dispatch_history`) | Лимит — критичная часть бизнес-логики; без реального движка тестировать его смысла нет. |
| Идемпотентность `alerting:{rule_id}:{run_id}` в `notifications.adm_create_task` | То же. |
| Партиционирование `t_dispatch_history` по неделям + retention 90 дней | Сейчас обычная таблица; объём данных — нулевой. Логику партиционирования и крон удаления старых партиций имеет смысл подключать одновременно с реальной записью в эту таблицу. |
| Авто-разворачивание Superset-дашбордов из YAML/zip | На неделе 2 даны SQL в `superset/README.md`; импорт через `superset import-dashboards` — позже. |
| Юнит/интеграционные тесты движка (НФТ-6) | На неделе 2 движок — каркас, тестировать нечего. |
| Подключение alerting-engine к ELK / Glitchtip | JSON-логи в stdout уже пишутся (через `python-json-logger`), Sentry-init работает по env `ALERTING_SENTRY_DSN`. Полноценная проверка end-to-end — на неделе 3. |
| Наполнение колонок `t_rules.status` / `next_run_at` / `last_validation_error` (+ индекс `ix_t_rules_next_run`) | Схема заведена **авансом** под неделю 3 (валидация SQL-правила → `status='invalid'` + `last_validation_error`; персист расписания → `next_run_at`). На неделе 2 эти поля присутствуют в DDL и видны во вьюхе `v_rules`, но пока всегда `NULL` / `'active'` — кодом не наполняются. Заводим заранее, чтобы не переписывать applied-миграцию `0001_initial` на неделе 3. |

---

## 3. Решения, принятые сверх буквы ТЗ (согласованы с пользователем 2026-05-29)

### 3.1 Дедупликация `user_events` встроенными средствами StarRocks

**Что было:** `DUPLICATE KEY(request_id, user_id, event_type)` — дубли по
`request_id` сохраняются. Retry Routine Load или ретрай продьюсера
вставляют ту же запись повторно.

**Что стало:** `PRIMARY KEY (request_id, event_type)`. StarRocks при
конфликте PK выполняет REPLACE (UPSERT) — повторная вставка не создаёт
второй строки. `enable_persistent_index = true` — рекомендация
StarRocks для PK-таблиц с высоким write-throughput.

**Почему так:** дедупликация дешевле всего на уровне транспорта.
Правила в `alerting` свободно `SELECT count(DISTINCT user_id)` без
страха посчитать одно событие дважды.

### 3.2 `dim_date` поверх ранее неиспользуемого `content.date_dimension`

В `admin-panel-service/movies/models.py` уже есть Django-модель
`DateDimension` (PK = `date`, ~91 тысячи строк с 1800 по 2050: `year`,
`quarter`, `is_weekend`, `is_holiday`, `day_of_week`...). В коде проекта
она ни в одном запросе **не используется**.

В рамках диплома задействуем её: создаём `ugc_analytics.dim_date`,
синхронизируем из Postgres одноразовым `SUBMIT TASK sync_dim_date` (без
расписания — таблица растёт ровно на одну строку в сутки). На её основе
строим `mv_weekend_film_activity` (join `user_events ⋈ dim_date.is_weekend`)
и третий чарт Superset «выходные vs будни».

Это даёт правилам единообразный способ выражать «по выходным», «по пятницам»,
«в праздничные дни» — без дублирования логики date-арифметики в каждом SQL.

### 3.3 Новый event_type `recommendation` в activity-tracker

`POST /ugc/api/v1/events/recommendation` принимает реакции пользователя
на письма от alerting (`opened / clicked / dismissed`) + `rule_code` +
`notification_message_id`. Топик `recommendations`, Routine Load
`recommendations_load` записывает в ту же таблицу `user_events`
(колонки `rule_code / notification_message_id / action`).

Замыкает контур: «событие → витрина → правило → задача → письмо → клик
→ событие». Аналитик в Superset может посчитать конверсию собственного
правила одним SQL по `ugc_analytics.user_events WHERE event_type='recommendation'
AND rule_code=...`.

### 3.4 Apache Superset 6.1.0 (актуальная версия)

Релиз 6.1.0 — 2026-05-13. Используем актуальный вместо первой попавшейся
ветки 4.x. Содержит фичу `EMBEDDED_SUPERSET` (потенциально пригодится,
если решим встраивать чарты в admin-panel) и DASHBOARD_NATIVE_FILTERS.

---

## 4. Архитектурные акценты для защиты

### 4.1 Почему `dim_*` синхронизируются через JDBC Catalog внутри StarRocks, а не отдельным Python-сервисом

В проекте уже есть прецедент Python-ETL (`films-etl-service` для
Elasticsearch). Для `alerting` поступаем иначе: используем нативный
механизм StarRocks (JDBC Catalog + `SUBMIT TASK SCHEDULE`). Преимущества:

- **Минус один сервис в стеке.**
- **Парность с Routine Load:** для потокового канала — Routine Load,
  для пакетной перезаливки — `SUBMIT TASK`. Одна и та же модель
  «оркестрация внутри StarRocks».
- **Правильный DWH-нарратив** для защиты: аналитик видит, что dim-таблицы
  всегда свежие, и не задаёт лишних вопросов про ETL-задержки.

Отдельный Python-сервис был бы оправдан при CDC или сложных
преобразованиях. Для трёх плоских таблиц с полной перезаливкой раз
в час это избыточно.

### 4.2 Почему SQL-функции в Postgres вместо REST

Целевой пользователь — продуктовый аналитик в DBeaver, ему удобнее
`SELECT alerting.adm_create_rule(...)`, чем `curl`. Меньше слоёв
(Pydantic → FastAPI → ORM → SQL), меньше кода. REST оставлен в §12
«Возможные улучшения» в основном ТЗ — реализуется тонкой обёрткой
поверх тех же функций без дублирования логики.

### 4.3 Демо-режим `dim_*`: ручной `EXECUTE TASK` на защите

`SUBMIT TASK ... SCHEDULE EVERY 1 HOUR` — производственный интервал.
На защите аналитик не должен ждать час, поэтому в `examples.sql` есть
готовый блок:

```sql
USE ugc_analytics;
EXECUTE TASK sync_dim_users;
EXECUTE TASK sync_dim_films;
EXECUTE TASK sync_dim_genres;
EXECUTE TASK sync_dim_date;
REFRESH MATERIALIZED VIEW mv_user_activity;
-- ...и т.д. для остальных MV
```

Понижать интервал расписания в дамп-конфигурации не стали — это исказило
бы прод-вид DDL.

### 4.4 Идемпотентность `demo-tools`

`seed-users` сначала `DELETE FROM auth.users WHERE is_demo`, потом
`INSERT N штук`. Каскадом удаляются `refresh_tokens`, `user_roles`,
`user_oauth_providers` тех же юзеров. Реальные пользователи не
затрагиваются (фильтр по `is_demo=TRUE`).

`trigger-events` безопасно перезапускать — `user_events` теперь
PK-таблица, повторный `request_id` не даст второй строки.

---

## 5. Порядок зависимостей в `docker-compose`

При полном старте `docker compose up -d --build` критичные звенья:

```
movies-db (healthy)
  ↓
movies-notifications-migrations (completed)
  ↓
movies-alerting-migrations (completed)        ← регистрирует шаблоны через notifications.adm_*
  ↓
movies-alerting-engine (running)

movies-starrocks (healthy)
  ↓
movies-starrocks-init (completed)             ← user_events + Routine Load
  ↓                              ↑
movies-starrocks-dims-init       movies-auth-service (healthy, миграция полей сегментации применена)
  ↓
movies-superset (running)
```

Если что-то не успело подняться, всегда можно вручную:
`docker compose restart movies-alerting-engine` — он подхватит правила.

---

## 6. Обновления документов

- `diploma_tz_short.md` — секция «Что добавляется/меняется» дополнена
  пунктами про `dim_date`, дедупликацию `user_events`, новый event_type
  `recommendation`, Superset 6.1.0.
- `diploma_tz.md` — соответствующие правки в §6 (архитектура), §9.2
  (StarRocks: новые dim/mv и PK-table), §10 (сценарий weekend_burst).
- Корневой `README.md` — таблица сервисов и URL дополнена новыми
  компонентами; Superset → http://localhost:8088.
- `.env.template` — блоки `ALERTING_*`, `SUPERSET_*`, `DEMO_*`.

---

## 7. Чек-лист для defense run-through (быстрая проверка стека)

```bash
docker compose down -v
docker compose up -d --build

# 1. Все init-контейнеры завершились с кодом 0
docker compose ps | grep -E '(migrations|init)'

# 2. Movies-alerting-engine логирует tick'и (раз в минуту, если есть включённые правила)
docker compose logs --tail=20 movies-alerting-engine

# 3. Postgres:
psql -h localhost -p 5438 -U postgres -d movies -c \
  "SELECT id::text, code FROM alerting.t_rules ORDER BY created_at;"

# 4. StarRocks:
mysql -h localhost -P 9030 -uroot -e "
  USE ugc_analytics;
  SHOW CATALOGS;
  SELECT count(*) FROM dim_films;
  SELECT count(*) FROM dim_date;
  SHOW TASKS\G
  SHOW MATERIALIZED VIEWS;
  DESCRIBE user_events;"

# 5. Demo:
docker compose --profile demo run --rm movies-demo-tools seed-users --count 30
docker compose --profile demo run --rm movies-demo-tools trigger-events --scenario winback --count 20

# 6. Superset:
open http://localhost:8088    # admin / admin → SQL Lab → starrocks_analytics
```

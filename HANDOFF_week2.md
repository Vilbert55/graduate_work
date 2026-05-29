# Handoff — конец недели 2 (сессия 2026-05-29)

Документ для переноса работы на другой компьютер. На текущем хосте подняться
до конца не удалось из-за дисковых ограничений (см. §5). Весь код запушен,
проверить нужно при свободном диске ≥ 30 GB.

---

## 1. Что сделано в этой сессии (после ревизии 2 плана)

### 1.1 Сменили статус сценариев в `diploma_tz.md` §10

- **§10.2 Сценарий A win-back** → помечен «(основной)»
- **§10.4 Сценарий C weekend burst** → помечен «(основной)»  
- **§10.3 Сценарий B тренд в сегменте** → помечен «(дополнительный)»

Преамбула §10 переформулирована: weekend_burst — обязательный сценарий
для защиты (демонстрирует архитектурное расширение `dim_date`).
`segment_trend` ушёл в дополнительные — самый сложный SQL.

### 1.2 Реализован минимальный end-to-end в `alerting-engine`

Замкнули кольцо «правило → SQL в StarRocks → задача в notifications → письмо».

**Новые файлы:**
- `alerting-service/src/services/__init__.py`
- `alerting-service/src/services/executor.py` — главный модуль исполнения:
  - `execute_rule(rule_id, run_id=None, dry_run=False)` — открывает соединение
    с StarRocks под `alert_reader`, выполняет SQL правила с тайм-аутом
    `ALERTING_STARROCKS_QUERY_TIMEOUT_SEC`, парсит колонку `user_id` из
    резалт-сета, дедуплицирует, обрезает по `max_users`, вызывает
    `notifications.adm_create_task` с идемпотентным ключом
    `alerting:{rule_id}:{run_id}`. Атомарно обновляет `t_runs` (running →
    success/failed) и `t_rules.last_run_at`.

**Обновлены:**
- `alerting-service/src/workers/engine.py` — добавлен фоновый listener на
  Postgres NOTIFY-канал `alerting_trigger`. Парсит payload вида
  `trigger:{rule_id}:{run_id}` или `dryrun:{rule_id}:{run_id}` и вызывает
  `execute_rule` с соответствующими параметрами. APScheduler-тик теперь
  тоже вызывает `execute_rule`, а не просто логирует.
- `alerting-service/sql/functions/006_adm_trigger_rule.sql` — функция
  теперь создаёт `t_runs` со статусом `running` и шлёт
  `pg_notify('alerting_trigger', 'trigger:<rule_id>:<run_id>')`. Возвращает
  `run_id` сразу; результат — через `v_runs`.
- `alerting-service/sql/functions/005_adm_dry_run_rule.sql` — переписана с
  TABLE-возврата на `RETURNS UUID`. Аналогично шлёт NOTIFY с префиксом
  `dryrun:`. Движок выполнит SQL, посчитает `matched_users`, **не** вызовет
  `adm_create_task`. Аналитик поллит `v_runs WHERE run_id = ...`.
- `alerting-service/examples.sql` — обновлён пример dry-run (теперь UUID +
  поллинг `v_runs`).

### 1.3 Сознательные упрощения (всё равно неделя 3)

В `executor.py` в docstring явно перечислено:
- `frequency_cap` не применяется — лимит уведомлений по `t_dispatch_history` неделя 3.
- Per-user `context` из SQL правила игнорируется (`adm_create_task` принимает
  глобальные `params`, без per-user разлива). Шаблоны написаны с дефолтами
  через Jinja `default`, так что письма формируются корректно.
- Запись в `t_dispatch_history` построчно не делается (нет лимита — нет
  смысла; партиции и retention тоже неделя 3). Агрегат записывается в `t_runs`.
- Если перезапуск произойдёт *между* `pg_notify` и `execute_rule`, run
  останется в статусе `running` навсегда. Recovery worker — неделя 3.

### 1.4 Конфликты портов на хосте (как обойдены в `.env`)

На хосте уже работают чужие контейнеры `dps` + `dps-db`:
- `dps-db` слушает 5438 → мы поменяли `EXTERNAL_DB_PORT=5439` в `.env.template`
  (не подняли — пользователь должен пересоздать `.env` из template).

  **Не меняли в `.env.template`** — это шаблон, пусть пользователь сам решит.
  **Но в локальном `.env` (он в .gitignore)** на текущем хосте уже `5439`.
- `dps` слушает 8080 → меняли `kafka-ui` маппинг **в `docker-compose.yml`**
  на `"8081:8080"`. Этот коммит вошёл в репозиторий — на других машинах
  тоже будет 8081 (если порт 8080 свободен — измените обратно по желанию).

---

## 2. Структура коммитов сессии (после `git log --oneline`)

```
HEAD  (после фиксации недели 2 ревизия 2)
606feca auth: add segmentation fields
2fd52e1 activity-tracker: add recommendation event type
004a1fe starrocks: switch user_events to Primary Key table
bc1a617 alerting: new service scaffold with schema, SQL-functions and engine
fe7ee15 starrocks: dim tables, JDBC Catalog, materialized views, alert_reader
cd0c897 demo-tools: seed-users and trigger-events CLI
7eca41c superset: Apache Superset 6.1.0 with StarRocks data source
aa72da5 docs: week 2 analytical note + README + diploma TZ updates
```

Этой сессии (предстоит закоммитить):
- `alerting: minimal end-to-end engine (real SQL → notifications.adm_create_task)`
- `docs: mark scenarios A/C as primary, B as optional; kafka-ui port 8081`

---

## 3. Что проверить на другом компьютере

### 3.1 Подготовка

```bash
git pull
cp .env.template .env

# Сгенерировать SUPERSET_SECRET_KEY
SK=$(openssl rand -hex 32)
sed -i "s|SUPERSET_SECRET_KEY=change_me_with_openssl_rand_hex_32|SUPERSET_SECRET_KEY=${SK}|" .env

# Если порт 5438 занят на хосте — поменять EXTERNAL_DB_PORT в .env
# Если порт 8081 занят — поправить kafka-ui в docker-compose.yml
```

**Свободного места:** не менее 30 GB на разделе с Docker (`/var/lib/docker`).
StarRocks отказывает в `CREATE TABLE`, если `MaxDiskUsedPct > storage_high_watermark_usage_percent` (95% по умолчанию).

### 3.2 Запуск

```bash
docker compose up -d --build
```

Сборка alerting-service / demo-tools / superset = ~5-10 минут.

### 3.3 Defense run-through (из `diploma_week2_notes.md` §7, обновлённый)

```bash
# 1) Init-контейнеры завершились с кодом 0
docker compose ps -a | grep -E '(init|migrations)' | grep -v 'Exited (0)' && echo "ALERT: что-то упало" || echo "OK"

# 2) Postgres — alerting и notifications развёрнуты
docker exec movies-db psql -U postgres -d movies -c \
  "\df alerting.adm_*"
docker exec movies-db psql -U postgres -d movies -c \
  "SELECT proname FROM pg_proc WHERE pronamespace='notifications'::regnamespace AND proname='adm_create_task';"

# 3) StarRocks — все 4 dim + 5 mv + PK user_events + JDBC catalog
docker exec movies-starrocks mysql -h127.0.0.1 -P9030 -uroot -e "
  USE ugc_analytics;
  SHOW CATALOGS;
  SELECT count(*) FROM dim_films;     -- ~999
  SELECT count(*) FROM dim_genres;    -- ~26
  SELECT count(*) FROM dim_date;      -- ~91051
  SHOW TASKS\G                        -- 3+1 SUBMIT TASK
  SHOW MATERIALIZED VIEWS;            -- 5 mv_*
  DESCRIBE user_events;               -- PRIMARY KEY (request_id, event_type)
  SHOW ROUTINE LOAD\G                 -- 4 загрузчика (views/clicks/custom/recommendations)
"

# 4) Demo-seeder создаёт пользователей
docker compose --profile demo run --rm movies-demo-tools \
    seed-users --count 30
# Должно быть: "OK: deleted previous is_demo users, created 30 new demo users"

# 5) Demo-trigger — основные сценарии
docker compose --profile demo run --rm movies-demo-tools \
    trigger-events --scenario winback --count 20
docker compose --profile demo run --rm movies-demo-tools \
    trigger-events --scenario weekend_burst --count 20

# 6) Через DBeaver или psql под postgres-пользователем создать роль и правило:
docker exec movies-db psql -U postgres -d movies <<'SQL'
CREATE USER alerting_admin_demo WITH PASSWORD 'demo';
GRANT alerting_admin TO alerting_admin_demo;

SELECT alerting.adm_create_rule(
    p_code := 'winback_demo',
    p_description := 'Демо: возврат угасших пользователей',
    p_sql := $sql$
        SELECT user_id
        FROM ugc_analytics.mv_user_activity
        WHERE was_active_last_month = TRUE
          AND last_watch_at < now() - INTERVAL 7 DAY
        $sql$,
    p_cron := '*/2 * * * *',  -- каждые 2 минуты для демо
    p_template_code := 'winback_recommendation',
    p_channel := 'email'
);
SELECT alerting.adm_enable_rule(
    (SELECT id FROM alerting.t_rules WHERE code='winback_demo')
);
SQL

# 7) Принудительно обновить MV (без часовой паузы)
docker exec movies-starrocks mysql -h127.0.0.1 -P9030 -uroot -e "
  USE ugc_analytics;
  EXECUTE TASK sync_dim_users;
  EXECUTE TASK sync_dim_films;
  EXECUTE TASK sync_dim_genres;
  EXECUTE TASK sync_dim_date;
  REFRESH MATERIALIZED VIEW mv_user_activity;
"

# 8) Подождать пару минут — engine сработает по cron */2
sleep 130
docker compose logs --tail=50 movies-alerting-engine | grep 'engine tick\|rule execution'

# Должно быть: "engine tick" → "rule execution finished status=success dispatched=N"

# 9) Письма в Mailpit
open http://localhost:8025

# 10) Superset → http://localhost:8088 (admin/admin)
#     Settings → Database Connections → starrocks_analytics
#     SQL Lab → выполнить запросы из superset/README.md
```

### 3.4 Ручная отладка end-to-end через `adm_trigger_rule`

Не дожидаясь cron:

```sql
-- Под пользователем с ролью alerting_admin
SELECT alerting.adm_trigger_rule(
    (SELECT id FROM alerting.t_rules WHERE code='winback_demo')
) AS run_id;

-- Через 2-5 секунд:
SELECT status, matched_users, dispatched_users, notification_task_id, error
FROM alerting.v_runs
WHERE run_id = '<вернувшийся run_id>';
```

---

## 4. Возможные проблемы

### 4.1 HTTP-прокси на хосте

На текущем хосте `HTTP_PROXY=http://127.0.0.1:12334` в shell.
- `docker pull`, `docker build` — Docker daemon **обычно** не наследует
  proxy от shell; проверить через `docker info | grep -i proxy`. Если
  настроен — pull/push идёт через прокси. Внутри билд-контейнеров
  `HTTPS_PROXY` тоже может пробрасываться, что обычно ок.
- **JDBC Catalog** в StarRocks скачивает `postgresql-42.7.4.jar` по
  HTTPS из <https://jdbc.postgresql.org>. Скачивает изнутри контейнера
  StarRocks. Если в контейнере нет прокси и интернет недоступен —
  падает с DNS/connection error при первом обращении к pg_catalog.
  **Workaround:** загрузить jar заранее во volume и в init.sql
  указать `"driver_url" = "file:///path/in/container/postgresql-42.7.4.jar"`.
- `curl localhost:8088` с хоста при `HTTP_PROXY` — пойдёт через прокси
  на 127.0.0.1:12334, который вряд ли проксирует на localhost.
  **Workaround:** `curl --noproxy '*' http://localhost:8088` или
  `unset HTTP_PROXY` перед curl.

### 4.2 Диск StarRocks

Если `df -h /` >= 95% — StarRocks BE откажет в `CREATE TABLE` с
ошибкой про disk watermark. Освободить диск или временно поднять
watermark:

```bash
docker exec movies-starrocks mysql -h127.0.0.1 -P9030 -uroot -e "
ADMIN SET FRONTEND CONFIG ('storage_high_watermark_usage_percent' = '99');
ADMIN SET FRONTEND CONFIG ('storage_flood_stage_usage_percent' = '99');
"
```

### 4.3 movies-notifications-rabbit-init Exited (1)

Race condition с RabbitMQ healthcheck. Перезапустить:
```bash
docker compose restart movies-notifications-rabbit-init
```

Дальше зависящие от него консьюмеры (`movies-notifications-email-sender-*`,
`movies-notifications-publisher`, `movies-notifications-ws-gateway`) должны
сами подняться (depends_on по completed_successfully).

### 4.4 Если миграция alerting упадёт с "function notifications.adm_upsert_template does not exist"

Это означает, что `movies-notifications-migrations` ещё не отработал, а
`movies-alerting-migrations` уже стартовал. depends_on в docker-compose
прописан правильно (`condition: service_completed_successfully`), но
ручной `docker compose up movies-alerting-migrations` обходит этот контракт.
Сначала:
```bash
docker compose up -d movies-notifications-migrations
# дождаться Exited (0)
docker compose up -d movies-alerting-migrations
```

---

## 5. Что НЕ удалось проверить на текущем хосте

Из-за `MaxDiskUsedPct=97.67%` на StarRocks BE (диск хоста переполнен)
не получилось пройти `CREATE TABLE ugc_analytics.user_events` →
вся цепочка `starrocks-init / starrocks-dims-init / alerting-engine`
не была запущена в end-to-end проверке. Все остальные компоненты до
этого момента поднимались успешно (`movies-db`, `movies-rabbitmq`,
`movies-kafka`, `movies-starrocks` healthy; `movies-auth-service`,
`movies-notifications-migrations`, `movies-alerting-migrations`
Exited(0)).

**Что точно работает (поднималось):**
- Postgres + schemas auth, notifications, alerting.
- Auth-миграция новой колонки `is_demo`/`gender`/`age_group`/`country`
  применилась.
- Alerting-миграция применилась (`t_rules`, `t_runs`, `t_dispatch_history`,
  все adm_*-функции, v_* представления, роль alerting_admin, шаблоны
  через notifications.adm_upsert_template).
- RabbitMQ healthy.
- Kafka + 4 топика (включая recommendations) созданы.

**Что нужно проверить отдельно (с другого компа со свободным диском):**
- Поднимается ли `movies-starrocks-init` (особо: PK-таблица user_events
  с `enable_persistent_index=true`).
- Поднимается ли `movies-starrocks-dims-init` (особо: скачивание
  PostgreSQL JDBC-драйвера — см. §4.1 про прокси).
- Реальный end-to-end правила: `adm_trigger_rule` → engine → SQL в
  StarRocks → `adm_create_task` → email в Mailpit.

---

## 6. Прогресс по неделе 2 (итог)

| Пункт ТЗ недели 2 | Статус |
|---|---|
| Миграция alembic auth-service | ✅ закоммичено (606feca) |
| Утилиты demo-seeder / event-trigger | ✅ закоммичено (cd0c897) |
| Init-контейнер StarRocks (DDL + JDBC Catalog + SUBMIT TASK) | ✅ закоммичено (fe7ee15), требует disk space для верификации |
| Миграции схемы alerting | ✅ закоммичено (bc1a617) |
| SQL-функции управления правилами | ✅ закоммичено (bc1a617) |
| Минимальный движок (заготовка) | ✅ закоммичено (bc1a617) + end-to-end на этой сессии |
| Superset | ✅ закоммичено (7eca41c), требует verifyu |
| Аналитическая записка | ✅ `diploma_week2_notes.md` (aa72da5) |
| Обновление ТЗ | ✅ `diploma_tz.md` / `diploma_tz_short.md` (aa72da5 + этой сессии) |

Сверх ТЗ дополнительно реализовано:
- Дедупликация `user_events` через PK table StarRocks.
- `dim_date` поверх ранее неиспользуемого `content.date_dimension`.
- Event_type `recommendation` в activity-tracker для конверсии правил.
- Реальный end-to-end в движке (планировалось на неделю 3): `_tick`
  выполняет SQL и зовёт `notifications.adm_create_task` с идемпотентным
  ключом; `adm_trigger_rule` и `adm_dry_run_rule` работают через
  LISTEN/NOTIFY и реально исполняются движком.

---

## 7. План недели 3 (что осталось из ТЗ)

- Frequency cap (`per_rule_per_user_days`, `per_user_per_day`) с проверкой
  по `t_dispatch_history`.
- Партиционирование `t_dispatch_history` по неделям + retention 90 дней.
- Per-user context (потребует расширения notifications-service или per-user
  task split).
- Recovery worker для случаев "engine упал между NOTIFY и execute_rule".
- Юнит/интеграционные тесты движка (НФТ-6).
- Полная подсветка ELK (alerting-engine структурно логирует, нужно
  проверить, что Filebeat это собирает) и Glitchtip (sentry-init работает).
- Автоматический импорт Superset-дашбордов из YAML/zip (на неделе 2 даны
  только SQL для SQL Lab).
- Демо ревьюеру / наставнику.

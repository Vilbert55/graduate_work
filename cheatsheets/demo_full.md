# Сценарий демонстрации (запись видео)

Шпаргалка для записи экрана по всей дипломной части: замкнутый контур от события
пользователя до доставленного письма, со всеми возможностями — per-user контекст в
письме, лимит уведомлений, история доставки с партициями, восстановление после
сбоя, BI в Superset.

Обозначения по ходу файла:
- 🎬 **Показать** — то, что попадает в кадр видео.
- 🔍 **Проверка (для себя)** — контроль, что всё работает; в видео можно не показывать.

Весь SQL выполняется в **DBeaver** (наглядно), а не в `docker exec`. БД-операции
StarRocks под `root` — в отдельном подключении DBeaver. Готовые запросы аналитика
лежат в `alerting-service/examples.sql`.

Контур целиком (последняя строка — замыкание петли: реакция возвращается событием):
```
seed-users -> trigger-events -> Kafka -> Routine Load -> user_events
   -> REFRESH mv_* -> adm_create_rule -> dry-run -> adm_trigger_rule
   -> frequency cap -> t_dispatch_history -> notifications.adm_create_task (per-user context)
   -> RabbitMQ -> email-sender -> Mailpit
   -> клик по ссылке в письме -> GET /ugc/email/click -> recommendation-событие -> Kafka -> user_events
   -> dispatch_log + mv_rule_conversion -> воронка «отправили -> перешли по ссылке» в Superset
```

---

## 0. Подготовка: подключения DBeaver и GUI

🎬 Показать в начале видео три подключения DBeaver и вкладки браузера.

**DBeaver — три подключения:**

| Имя | Драйвер | Хост:порт | БД | Логин / пароль |
|---|---|---|---|---|
| `movies-pg` (alerting/notifications) | PostgreSQL | `localhost:5438` | `movies` | `postgres` / *(POSTGRES_PASSWORD из `.env`)* |
| `starrocks-reader` (аналитик) | MySQL | `localhost:9030` | `ugc_analytics` | `alert_reader` / `alert_reader` |
| `starrocks-root` (админ витрин) | MySQL | `localhost:9030` | `ugc_analytics` | `root` / *(пусто)* |

> StarRocks говорит по MySQL-протоколу, поэтому в DBeaver выбираем драйвер **MySQL**
> и указываем порт `9030`. Для роли `alert_reader` доступен только SELECT — это и
> показывает, что правило аналитика физически не может ничего изменить.

**Браузер — вкладки:**

| GUI | URL | Логин |
|---|---|---|
| Mailpit (приёмник писем) | http://localhost:8025 | — |
| Superset (BI) | http://localhost:8088 | `admin` / `admin` |
| Kafka UI | http://localhost:8081 | — |
| RabbitMQ | http://localhost:15672 | `guest` / `guest` |

---

## 1. Поднять стек

```bash
cd ~/praktikum/graduate_work
docker compose up -d --build        # StarRocks поднимается ~1–2 мин
```

🔍 **Проверка (для себя):**
```bash
# Все init/migrations завершились с кодом 0
docker compose ps -a --format '{{.Name}}\t{{.Status}}' \
  | grep -E '(init|migrations)' | grep -v 'Exited (0)' \
  && echo "ВНИМАНИЕ: что-то упало" || echo "OK"

# Движок поднялся: планировщик + слушатель + обслуживание партиций
docker compose logs movies-alerting-engine | grep -E 'started|maint|listening'
```
Ожидаем в логах: `alerting-engine started`, job `maint_dispatch_partitions`,
`listening for triggers`.

---

## 2. Засеять демо-данные (терминал)

🎬 Показать команды и их вывод.
```bash
# 50 демо-юзеров в auth.users (is_demo=TRUE, с gender/age/country/email)
docker compose --profile demo run --rm movies-demo-tools seed-users --count 50

# Паттерн win-back: каждому 10–15 view-событий 30..8 дней назад, затем тишина 7 дней
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario winback --count 30
```
> Если демо-образ давно не пересобирался — добавьте `--build` к `run`.

🎬 **Показать в Kafka UI** (http://localhost:8081): топик `views` наполнился —
видно рост сообщений. Это наглядно демонстрирует, что события идут через Kafka.

🔍 **Проверка (для себя)** — события долетели в StarRocks через Routine Load.
В DBeaver (`starrocks-reader`):
```sql
SELECT count(*) FROM ugc_analytics.user_events;   -- сотни событий
```

---

## 3. Обновить витрины StarRocks (DBeaver: `starrocks-root`)

В демо не ждём часовой `SUBMIT TASK` — синхронизируем измерения и витрины вручную.
StarRocks 4.0.8 не поддерживает `EXECUTE TASK <имя>`, поэтому повторяем тот же
`INSERT OVERWRITE`, что и в `SUBMIT TASK`, + `REFRESH ... WITH SYNC MODE` (полный
блок — `examples.sql` §7). `dim_films/dim_genres` уже наполнил init-контейнер;
обновляем `dim_users` (свежие демо-юзеры) и win-back MV.

🎬 Выполнить в подключении `starrocks-root`:
```sql
USE ugc_analytics;

INSERT OVERWRITE dim_users
SELECT CAST(u.id AS VARCHAR(36)), u.gender, u.age, u.country,
       concat_ws('_', coalesce(u.gender,'X'),
           CASE WHEN u.age IS NULL THEN 'X'
                WHEN u.age < 18 THEN '0-17' WHEN u.age <= 24 THEN '18-24'
                WHEN u.age <= 34 THEN '25-34' WHEN u.age <= 44 THEN '35-44'
                WHEN u.age <= 54 THEN '45-54' ELSE '55+' END,
           coalesce(u.country,'X')),
       u.created_at, u.is_demo
FROM pg_catalog.auth.users u;

REFRESH MATERIALIZED VIEW mv_user_activity   WITH SYNC MODE;
REFRESH MATERIALIZED VIEW mv_user_top_genres WITH SYNC MODE;
```

🔍 **Проверка (для себя)** — сколько юзеров попадёт под правило win-back:
```sql
SELECT count(*) FROM ugc_analytics.mv_user_activity a
JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
WHERE a.was_active_last_month = TRUE AND a.last_watch_at < now() - INTERVAL 7 DAY;
-- ~20
```

---

## 4. Зарегистрировать правило (DBeaver: `movies-pg`)

🎬 Сначала показать, что выборка работает (подключение `starrocks-reader`):
```sql
USE ugc_analytics;
SELECT user_id,
       -- named_struct строит структуру ключ-значение, to_json делает из неё JSON-
       -- строку: это и есть per-user context, который подставится в письмо
       to_json(named_struct('top_genres', t.top_genres)) AS context
FROM ugc_analytics.mv_user_activity a
JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
WHERE a.was_active_last_month = TRUE
  AND a.last_watch_at < now() - INTERVAL 7 DAY;
```

🎬 Теперь регистрируем правило (подключение `movies-pg`). SQL правила обязан вернуть
`user_id` и опционально `context`; здесь `context` несёт top-3 жанра пользователя.
```sql
SELECT alerting.adm_create_rule(
    p_code          := 'winback_active_user',
    p_description   := 'Возврат угасших активных зрителей',
    p_sql           := $sql$
        SELECT user_id,
               to_json(named_struct('top_genres', t.top_genres)) AS context
        FROM ugc_analytics.mv_user_activity a
        JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
        WHERE a.was_active_last_month = TRUE
          AND a.last_watch_at < now() - INTERVAL 7 DAY
        $sql$,
    p_cron          := '0 9 * * *',
    p_template_code := 'winback_recommendation',
    p_channel       := 'email',
    -- общий дневной потолок на пользователя — настройка движка
    -- ALERTING_GLOBAL_PER_USER_PER_DAY (по умолчанию 3), а не поле правила
    p_frequency_cap := '{"per_rule_per_user_days": 30}'::jsonb,
    p_max_users     := 50000
);
SELECT alerting.adm_enable_rule('winback_active_user');
```

🎬 **Показать валидацию** (ФТ-1, НФТ-2) — осмысленные ошибки на «кривых» входах:
```sql
-- канал не из списка
SELECT alerting.adm_create_rule('x','x','SELECT user_id FROM t','0 9 * * *',
        'winback_recommendation','telegram');            -- invalid_channel

-- SQL не на чтение
SELECT alerting.adm_create_rule('x','x','DELETE FROM t','0 9 * * *',
        'winback_recommendation','email');               -- invalid_sql: must start with SELECT or WITH

-- SQL без user_id
SELECT alerting.adm_create_rule('x','x','SELECT 1 FROM t','0 9 * * *',
        'winback_recommendation','email');               -- invalid_sql: must return column user_id

-- устаревший ключ лимита
SELECT alerting.adm_create_rule('x','x','SELECT user_id FROM t','0 9 * * *',
        'winback_recommendation','email',
        '{"per_user_per_day": 1}'::jsonb);                -- per_user_per_day is now a global engine setting
```

---

## 5. Тестовый прогон — dry-run (ФТ-5)

🎬 Подключение `movies-pg`:
```sql
SELECT alerting.adm_dry_run_rule('winback_active_user');
-- через 1–2 сек:
SELECT status, matched_users, after_cap_users, dispatched_users, is_dry_run
FROM alerting.v_runs ORDER BY started_at DESC LIMIT 1;
```
Ожидаем: `status=success, matched_users=20, after_cap_users=20, dispatched_users=0, is_dry_run=t`.

> Движок выполнил SQL в StarRocks, посчитал аудиторию **до и после лимита**, но
> `adm_create_task` НЕ вызвал — писем нет. `is_dry_run=t` отличает тестовый прогон.
> Dry-run заодно служит реальной проверкой SQL: если запрос не исполним в StarRocks,
> запуск уйдёт в `failed` с текстом ошибки в `v_runs.error`.

---

## 6. Боевой запуск (ФТ-6/7) и per-user контекст (ФТ-2)

🎬 Подключение `movies-pg`:
```sql
SELECT alerting.adm_trigger_rule('winback_active_user');
-- через 2–3 сек:
SELECT status, matched_users, after_cap_users, dispatched_users,
       notification_task_id IS NOT NULL AS has_task
FROM alerting.v_runs WHERE is_dry_run=FALSE ORDER BY started_at DESC LIMIT 1;
```
Ожидаем: `success, 20, 20, 20, has_task=t`.

🎬 **Показать письма в Mailpit** (http://localhost:8025): 20 писем с темой
«<Имя>, мы соскучились!». Открыть 2–3 письма — строка с жанрами **у каждого своя**:
реальные top-3 пользователя из его `context` (ФТ-2), а не дефолт шаблона.

🔍 **Проверка (для себя)** — отрендеренные тела (DBeaver `movies-pg`):
```sql
SELECT recipient_address, (regexp_match(body,'любимых жанров:\s*(.+)'))[1] AS genres
FROM notifications.t_messages
WHERE task_id=(SELECT id FROM notifications.t_tasks ORDER BY created_at DESC LIMIT 1)
ORDER BY recipient_address LIMIT 5;
```

> Как работает per-user контекст: движок одной **атомарной транзакцией** Postgres
> пишет `t_dispatch_history`, кладёт per-user контекст в `audience.params_by_user` и
> зовёт `notifications.adm_create_task`. Scheduler notifications мерджит
> `params_by_user[user_id]` поверх общих `params` при рендере Jinja. Схемы `alerting`
> и `notifications` в одной БД — поэтому всё в одной транзакции.

---

## 7. Лимит уведомлений — frequency cap (ФТ-3)

🎬 Запустим правило ещё раз сразу (подключение `movies-pg`):
```sql
SELECT alerting.adm_trigger_rule('winback_active_user');
-- через 2–3 сек:
SELECT started_at::time(0), matched_users, after_cap_users, dispatched_users
FROM alerting.v_runs WHERE is_dry_run=FALSE ORDER BY started_at DESC LIMIT 2;
```
Ожидаем у **нового** запуска: `matched_users=20, after_cap_users=0, dispatched_users=0`.

> Все 20 получили это правило только что -> сработал уровень `per_rule_per_user_days=30`
> (не чаще раза в 30 дней по этому правилу). Второй уровень — общий потолок на
> пользователя в сутки по ВСЕМ правилам — это **глобальная настройка движка**
> `ALERTING_GLOBAL_PER_USER_PER_DAY` (по умолчанию 3), а не поле правила. Новых строк
> в `t_dispatch_history` нет, второго письма никто не получил.

🎬 В Mailpit новых писем не появилось — наглядно.

---

## 8. История доставки и партиции (ФТ-8)

🎬 Подключение `movies-pg`:
```sql
-- Журнал отправок (для аудита/разбора жалоб)
SELECT rule_code, user_id, channel, sent_at FROM alerting.v_dispatch
ORDER BY sent_at DESC LIMIT 5;

-- Строки лежат в недельной партиции
SELECT tableoid::regclass AS partition, count(*)
FROM alerting.t_dispatch_history GROUP BY 1;

-- Список нарезанных партиций (этой и следующей недели)
SELECT c.relname FROM pg_inherits i
JOIN pg_class c ON c.oid=i.inhrelid
JOIN pg_class p ON p.oid=i.inhparent
WHERE p.relname='t_dispatch_history' ORDER BY 1;
```

### Где задаётся «нарезать по неделям» и как обслуживается

> **Это партиционирование на стороне Postgres** (таблица `t_dispatch_history`), не
> StarRocks. В StarRocks `user_events` партиций нет (PK + HASH-раздача).

- **Где «по неделям»:** в миграции `alembic/versions/0001_initial.py` таблица
  создаётся как `... PARTITION BY RANGE (sent_at)` (raw DDL — `op.create_table` не
  умеет PARTITION BY).
- **Кто нарезает партиции:** функция `alerting.maint_dispatch_partitions(N)`
  (`sql/functions/007_maint_dispatch_partitions.sql`): гарантирует партиции на
  текущую и следующую неделю (`date_trunc('week', now())`, шаг 7 дней; имя
  `t_dispatch_history_pYYYYMMDD` по понедельнику ISO-недели) и дропает партиции
  старше `now - retention`.
- **Когда вызывается:** движок зовёт её при старте и затем по cron `5 0 * * *`
  (раз в сутки), retention из `ALERTING_DISPATCH_RETENTION_DAYS` (90 дней). Первая
  нарезка — прямо в миграции (`SELECT alerting.maint_dispatch_partitions(90)`).

🎬 (Опционально) показать retention в действии: создать «старую» партицию и вызвать
обслуживание — она удалится (подключение `movies-pg`):
```sql
CREATE TABLE alerting.t_dispatch_history_p20260105
  PARTITION OF alerting.t_dispatch_history FOR VALUES FROM ('2026-01-05') TO ('2026-01-12');
SELECT alerting.maint_dispatch_partitions(90);   -- p20260105 пропадёт (конец недели старше 90 дней)
```

---

## 9. Восстановление после сбоя (НФТ-3) — рассказать, не показывать вживую

В видео достаточно объяснить словами + показать места в коде; живой рестарт не
демонстрируем.

**Как обеспечивается.** Срабатывание идёт в три фазы (`src/services/executor.py`,
`execute_rule`): (1) пометить запуск `running` отдельным коммитом; (2) выборка из
StarRocks; (3) **одной транзакцией** — cap, запись `t_dispatch_history`,
`notifications.adm_create_task`, финализация запуска. Пока статус `running`, по
запуску ничего не закоммичено. При старте движок (`_recover_interrupted_runs` в
`src/workers/engine.py`) берёт `running`-запуски старше `recovery_grace_sec` и
повторяет `execute_rule` с тем же `run_id` — атомарность фазы 3 гарантирует
отсутствие дублей. Вторая страховка — идемпотентный ключ `alerting:{rule_id}:{run_id}`
в `adm_create_task`: даже двойное восстановление вернёт ту же задачу, без второго
письма. Dry-run-запуски recovery не трогает (`t_runs.is_dry_run`).

🔍 **Самопроверка (для себя, не на видео)** — сымитировать прерванный запуск:
```sql
-- подключение movies-pg
DELETE FROM alerting.t_dispatch_history;   -- чтобы recovery было видно по факту рассылки
INSERT INTO alerting.t_runs(rule_id, status, started_at, is_dry_run)
SELECT id, 'running', (now() AT TIME ZONE 'utc') - interval '10 minutes', FALSE
FROM alerting.t_rules WHERE code='winback_active_user' RETURNING id;   -- запомнить run_id
```
```bash
docker restart movies-alerting-engine          # в логах: "recovering interrupted run"
```
```sql
SELECT status, dispatched_users FROM alerting.t_runs WHERE id='<run_id>';  -- success, 20
SELECT count(*) FROM alerting.t_dispatch_history;                          -- снова 20, без дублей
```

---

## 10. BI поверх витрин — Superset (браузер, http://localhost:8088)

Superset читает **те же materialized views** StarRocks под ролью `alert_reader` —
единый аналитический слой и для правил, и для дашбордов. `SELECT ... FROM mv_*` в
**SQL Lab** даёт только таблицу (сетку строк); чтобы получить график, из её
результата делается **Chart**.

🎬 **Живой чарт активности.** Войти `admin`/`admin` -> меню **SQL** -> **SQL Lab**.
Database `starrocks_analytics`, schema `ugc_analytics`. Выполнить:
```sql
SELECT bucket_hour, sum(views) AS views
FROM ugc_analytics.mv_film_watch_hourly
WHERE bucket_hour > now() - INTERVAL 30 DAY     -- 30 дней: win-back-события 8..30 дней назад
GROUP BY bucket_hour
ORDER BY bucket_hour;
```
Появится таблица -> кнопка **CREATE CHART** -> экран **Explore**: тип `Line Chart`,
X-axis `bucket_hour`, Metric `views` -> **CREATE CHART** -> **SAVE**. Линия повторяет
сгенерированный паттерн (всплеск 30..8 дней назад, провал в последнюю неделю) —
видно, что чарт показывает реальные засеянные события.

> Окно именно 30 дней: win-back-события лежат 8..30 дней назад, в окне «7 дней» чарт
> был бы пустым.

> Альтернатива SQL Lab: **Data -> Datasets -> + Dataset**, выбрать `ugc_analytics.mv_*`
> датасетом, затем **Charts -> + Chart** поверх него — без ручного SQL.

Главный чарт — воронка «отправили -> перешли по ссылке» — в следующем разделе.
Его и показываем «меняющимся вживую». Ещё готовые SQL (сегменты, выходные/будни) —
`superset/README.md`.

---

## 11. Замыкание петли — переход по ссылке из письма

Главная идея диплома: контур замыкается. В каждом письме win-back есть ссылка
«Открыть подборку». Пользователь кликает её прямо в почте — браузер дёргает
эндпоинт `GET /ugc/email/click` в activity-tracker, тот публикует событие
`recommendation` (`action=clicked`) в Kafka, и оно Routine Load'ом возвращается в
`user_events`. Так настоящий клик из письма виден в Superset — без синтетики.

Ссылка персональная — `http://localhost/ugc/email/click?rule=<код>&user=<uuid>&run=<id>`
(шаблон подставляет `{{ params.rule_code }}`, `{{ user.id }}`, `{{ params.run_id }}`).
Переход идемпотентен: `request_id` события = `uuid5(rule, run, user)`, поэтому повтор
клика по той же ссылке дубля не создаёт, а новый запуск правила (новый `run`) даёт
новую ссылку — отдельный переход (старые письма не задваиваются с новыми).

**Воронка:** отправлено (`dispatch_log`) -> перешли по ссылке (реакции).
«Отправлено» живёт в Postgres (`t_dispatch_history`), а Superset/правила ходят
только в StarRocks — поэтому журнал отправок копируется в StarRocks тем же
JDBC-механизмом, что и `dim_*` (таблица `dispatch_log`), а витрина
`mv_rule_conversion` джойнит его с реакциями.

🎬 **Шаг 1. Пустая воронка (письма ушли, переходов ещё нет).** Перенести журнал
отправок в StarRocks и посчитать витрину (подключение `starrocks-root`):
```sql
USE ugc_analytics;
INSERT OVERWRITE dispatch_log
SELECT r.code, CAST(d.user_id AS VARCHAR(36)), d.sent_at, d.channel
FROM pg_catalog.alerting.t_dispatch_history d
JOIN pg_catalog.alerting.t_rules r ON r.id = d.rule_id;
REFRESH MATERIALIZED VIEW mv_rule_conversion WITH SYNC MODE;
```
В Superset SQL Lab построить **Funnel Chart** (Database `starrocks_analytics`):
```sql
SELECT 'отправлено' AS stage, sent_users AS users
FROM ugc_analytics.mv_rule_conversion WHERE rule_code='winback_active_user'
UNION ALL
SELECT 'перешли по ссылке', clicked_users
FROM ugc_analytics.mv_rule_conversion WHERE rule_code='winback_active_user';
```
**CREATE CHART** -> тип `Funnel Chart`, Dimension `stage`, Metric `SUM(users)` ->
**SAVE**. Сейчас «перешли по ссылке» = 0 — письма ушли (`sent` = число из §6), но
никто ещё не кликнул.

🎬 **Шаг 2. Кликаем ссылки в письмах.** Открыть Mailpit (http://localhost:8025),
открыть выборочно несколько писем (например 5) и в каждом нажать ссылку «Открыть
подборку». Браузер покажет страницу «Спасибо! Уже подбираем для вас фильмы». Каждый
клик = реальный GET в activity-tracker -> событие `recommendation` в Kafka.

> Если в Mailpit ссылка не кликается — скопировать её в адресную строку браузера.

🎬 **Показать в Kafka UI** (http://localhost:8081): топик `recommendations`
наполнился ровно на число кликов — переходы реально прошли через шину.

🔍 **Проверка (для себя)** — переходы долетели в StarRocks (`starrocks-reader`):
```sql
SELECT count(DISTINCT user_id) FROM ugc_analytics.user_events
WHERE event_type='recommendation' AND action='clicked';   -- = сколько кликнули
```

🎬 **Шаг 3. Воронка наполняется.** Пересчитать витрину (`starrocks-root`):
```sql
USE ugc_analytics;
REFRESH MATERIALIZED VIEW mv_rule_conversion WITH SYNC MODE;
```
(`dispatch_log` не трогаем — отправки не менялись.) Нажать **RUN** на том же
Funnel-чарте: «перешли по ссылке» = 5 (или сколько кликнули). Видно **на глазах**:
из 17 отправленных столько-то реально перешли по ссылке из письма.

> ⚠️ Если «перешли по ссылке» = 0, хотя клики видны в Kafka UI (топик
> `recommendations`): значит Routine Load `recommendations_load` стоит на паузе и не
> забирает клики в `user_events`. Проверка: `SHOW ROUTINE LOAD FOR
> ugc_analytics.recommendations_load\G` — `PAUSED` с `unknown topic` означает гонку
> init (load создан раньше топика). Устранено зависимостью `movies-starrocks-init`
> от `movies-kafka-init` в `docker-compose.yml`; на уже поднятом стенде —
> `RESUME ROUTINE LOAD FOR ugc_analytics.recommendations_load;` (а если `Progress`
> ушёл к концу и `loadedRows=0` — `STOP` и пересоздать из `starrocks_init/init.sql`).

🎬 **Что это значит (сказать на видео).** Раньше после письма наступала тишина;
теперь виден реальный отклик — сколько людей кликнули ссылку из письма. Это
закрывает контур «данные -> письмо -> снова данные», и правила можно сравнивать
между собой по доле перешедших.

**Как это устроено (показать места в коде):**
- ссылка в шаблоне письма — `alerting-service/sql/seed/001_alerting_templates.sql`;
- приёмник кликов — `activity-tracker-service/src/api/v1/track.py`
  (`GET /ugc/email/click`). Публичный (получатель письма не авторизован) и лежит
  вне `/ugc/api/v1`, поэтому без JWT. В проде ссылку надо подписывать (HMAC), чтобы
  переход нельзя было подделать;
- `rule_code` и `run_id` в письмо кладёт движок (`executor._create_notification_task`,
  `params`), `user.id` подставляет рендер notifications;
- идемпотентность: `request_id` события = `uuid5(rule, run, user)` (`track.py`) — на
  PK `user_events` повтор клика схлопывается, а новый `run` = отдельный переход.

---

## 12. (Опционально) другие сценарии-витрины

Тот же конвейер, другие витрины/правила (полные SQL — `examples.sql`,
бизнес-истории — `diploma_tz.md` §10):
```bash
# Тренд в сегменте: всплеск просмотров фильма сегментом female_25-34_RU
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario segment_trend --segment female_25-34_RU --count 30
# Выходной всплеск: события только в субботу-воскресенье прошлой недели
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario weekend_burst --count 30
```
После каждого — refresh соответствующих MV (см. §3) и регистрация правила.

---

## Сброс перед повторным показом

```sql
-- подключение movies-pg
SELECT alerting.adm_delete_rule('winback_active_user');   -- полное удаление (правило + история)
```
Mailpit чистится кнопкой «Delete all». `seed-users`/`trigger-events` идемпотентны,
а повторный клик по ссылке из письма не создаёт дубля (детерминированный
`request_id`) — §2–§11 можно прогнать заново. Таблицы `dispatch_log`/
`mv_rule_conversion` пересоздаются при `docker compose down -v && up --build`.

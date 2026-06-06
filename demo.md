# Демонстрация alerting-service (недели 2–3)

Полная ручная демонстрация замкнутого контура: от события пользователя до
доставленного письма, со всеми возможностями недели 3 — per-user контекст в
письме, лимит уведомлений, история доставки с партициями, восстановление после
сбоя.

Контур целиком:
```
seed-users → trigger-events → Kafka → Routine Load → user_events
   → REFRESH mv_* → adm_create_rule → (dry-run) → adm_trigger_rule
   → frequency cap → t_dispatch_history → notifications.adm_create_task (per-user context)
   → RabbitMQ → email-sender → Mailpit
```

Инструменты: **терминал**, **DBeaver** (или `psql`), **браузер**, опц. **Postman**.

---

## 0. Доступы

| Что | Адрес | Логин / пароль |
|---|---|---|
| Postgres (схемы `alerting`, `notifications`, `auth`) | `localhost:5438`, БД `movies` | `postgres` / *(POSTGRES_PASSWORD из `.env`)* |
| StarRocks — аналитик (только SELECT) | MySQL-драйвер, `localhost:9030`, БД `ugc_analytics` | `alert_reader` / `alert_reader` |
| StarRocks — админ (REFRESH/INSERT OVERWRITE) | `localhost:9030` | `root` / *(пусто)* |
| Mailpit (приёмник писем) | http://localhost:8025 | — |
| Superset (BI) | http://localhost:8088 | `admin` / `admin` |
| Kafka UI | http://localhost:8081 | — |

> Шпаргалка аналитика с готовыми запросами — `alerting-service/examples.sql`.
> В примерах ниже команды к Postgres/StarRocks даны через `docker exec`, чтобы
> демо воспроизводилось без настройки DBeaver; в DBeaver те же SQL вводятся в
> окне запроса.

---

## 1. Поднять стек и проверить

```bash
cd ~/praktikum/graduate_work
docker compose up -d --build           # поднимет весь стек (StarRocks ~1–2 мин)

# Все init/migrations отработали с кодом 0?
docker compose ps -a --format '{{.Name}}\t{{.Status}}' \
  | grep -E '(init|migrations)' | grep -v 'Exited (0)' \
  && echo "ВНИМАНИЕ: что-то упало" || echo "OK: все init отработали"

# Движок поднялся (планировщик + слушатель + обслуживание партиций)?
docker compose logs movies-alerting-engine | grep -E 'started|maint|listening'
```

Ожидаем в логах движка: `alerting-engine started`, добавленный job
`maint_dispatch_partitions`, `listening for triggers`.

---

## 2. Засеять демо-пользователей и события (терминал)

```bash
# 50 демо-юзеров в auth.users (is_demo=TRUE, заполнены gender/age/country/email)
docker compose --profile demo run --rm movies-demo-tools seed-users --count 50

# Паттерн win-back: каждому 10–15 view-событий 30..8 дней назад, тишина 7 дней
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario winback --count 30
```

> Если демо-образ давно не пересобирался — добавьте `--build` к команде `run`.

**Проверка (StarRocks под `alert_reader`):** события долетели через Routine Load.
```bash
docker exec movies-starrocks mysql -uroot -P9030 -h127.0.0.1 -e \
  "SELECT count(*) FROM ugc_analytics.user_events;"     # сотни событий
```

---

## 3. Обновить витрины StarRocks (терминал, под `root`)

В демо не ждём часовой `SUBMIT TASK` — синхронизируем измерения и витрины вручную
(полный блок — в `alerting-service/examples.sql` §7). `dim_films`/`dim_genres`
уже наполнены init-контейнером; обновляем `dim_users` (свежие демо-юзеры) и MV
win-back.

```bash
docker exec movies-starrocks mysql -uroot -P9030 -h127.0.0.1 ugc_analytics -e "
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
REFRESH MATERIALIZED VIEW mv_user_top_genres WITH SYNC MODE;"
```

**Проверка:** сколько пользователей попадёт под правило win-back.
```bash
docker exec movies-starrocks mysql -uroot -P9030 -h127.0.0.1 -e "
SELECT count(*) FROM ugc_analytics.mv_user_activity a
JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
WHERE a.was_active_last_month = TRUE AND a.last_watch_at < now() - INTERVAL 7 DAY;"
# ~20
```

---

## 4. Зарегистрировать правило (Postgres)

`alerting-service/examples.sql` §2. SQL правила обязан вернуть колонку `user_id`
и опционально `context` (JSON). Здесь `context` несёт top-3 жанра пользователя —
это и подставится в письмо (ФТ-2).

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
    p_frequency_cap := '{"per_rule_per_user_days": 30, "per_user_per_day": 1}'::jsonb,
    p_max_users     := 50000
);
SELECT alerting.adm_enable_rule('winback_active_user');
```

> **Валидация (ФТ-1, НФТ-2).** Покажите осмысленные ошибки:
> `p_channel := 'telegram'` → `invalid_channel`; `p_cron := 'кривой'` → `invalid_cron`;
> несуществующий `p_template_code` → `template_not_found_or_inactive`.

---

## 5. Тестовый прогон — dry-run (ФТ-5)

```sql
SELECT alerting.adm_dry_run_rule('winback_active_user');
-- через 1–2 сек:
SELECT status, matched_users, after_cap_users, dispatched_users, is_dry_run
FROM alerting.v_runs ORDER BY started_at DESC LIMIT 1;
```
Ожидаем: `status=success, matched_users=20, after_cap_users=20, dispatched_users=0, is_dry_run=t`.

> Движок выполнил SQL в StarRocks, посчитал аудиторию **до и после лимита**, но
> `adm_create_task` НЕ позвал — писем нет. `is_dry_run=t` отличает тестовый
> прогон в журнале от боевого.

---

## 6. Боевой запуск (ФТ-6, ФТ-7) и per-user контекст (ФТ-2)

```sql
SELECT alerting.adm_trigger_rule('winback_active_user');
-- через 2–3 сек:
SELECT status, matched_users, after_cap_users, dispatched_users,
       notification_task_id IS NOT NULL AS has_task
FROM alerting.v_runs WHERE is_dry_run=FALSE ORDER BY started_at DESC LIMIT 1;
```
Ожидаем: `success, 20, 20, 20, has_task=t`.

**Письма дошли — браузер, Mailpit http://localhost:8025.** В инбоксе 20 писем
с темой «<Имя>, мы соскучились!». Откройте 2–3 письма: строка с жанрами **у
каждого своя** — реальные top-3 пользователя из его `context` (ФТ-2), а не дефолт
шаблона. Проверка из терминала по отрендеренным телам:

```bash
docker exec movies-db psql -U postgres -d movies -tAc "
SELECT recipient_address, (regexp_match(body,'любимых жанров:\s*(.+)'))[1]
FROM notifications.t_messages
WHERE task_id=(SELECT id FROM notifications.t_tasks ORDER BY created_at DESC LIMIT 1)
ORDER BY recipient_address LIMIT 3;"
```
Пример: у одного `Sci-Fi, Action, Comedy`, у другого `Music, Drama, Sci-Fi` — у
каждого свои.

> **Как это работает.** Движок одной **атомарной транзакцией** Postgres пишет
> `t_dispatch_history`, кладёт per-user контекст в `audience.params_by_user` и
> зовёт `notifications.adm_create_task`. Scheduler notifications мерджит
> `params_by_user[user_id]` поверх общих `params` при рендере Jinja. Схемы
> `alerting` и `notifications` в одной БД — поэтому всё в одной транзакции.

---

## 7. Лимит уведомлений — frequency cap (ФТ-3)

Запустим правило ещё раз сразу:

```sql
SELECT alerting.adm_trigger_rule('winback_active_user');
-- через 2–3 сек:
SELECT started_at::time(0), matched_users, after_cap_users, dispatched_users
FROM alerting.v_runs WHERE is_dry_run=FALSE ORDER BY started_at DESC LIMIT 2;
```
Ожидаем у **нового** запуска: `matched_users=20, after_cap_users=0, dispatched_users=0`.

> Все 20 пользователей получили это правило только что → сработал
> `per_rule_per_user_days=30` (не чаще раза в 30 дней). Второй уровень,
> `per_user_per_day=1` — общий потолок писем на пользователя в сутки по всем
> правилам. Новых строк в `t_dispatch_history` нет, второго письма никто не получил.

---

## 8. История доставки и партиции (ФТ-8)

```sql
-- Журнал отправок для аудита/разбора жалоб
SELECT rule_code, user_id, channel, sent_at FROM alerting.v_dispatch
ORDER BY sent_at DESC LIMIT 5;

-- Строки лежат в недельной партиции (PARTITION BY RANGE sent_at)
SELECT tableoid::regclass AS partition, count(*)
FROM alerting.t_dispatch_history GROUP BY 1;
```

Список партиций и обслуживание (под `postgres`):
```sql
-- партиции этой и следующей недели нарезаны автоматически
SELECT c.relname FROM pg_inherits i
JOIN pg_class c ON c.oid=i.inhrelid
JOIN pg_class p ON p.oid=i.inhparent
WHERE p.relname='t_dispatch_history' ORDER BY 1;

-- обслуживание: создать недельные партиции + дропнуть старше retention.
-- Движок зовёт это при старте и раз в сутки (ALERTING_DISPATCH_RETENTION_DAYS).
SELECT alerting.maint_dispatch_partitions(90);
```

> Демонстрация retention: создайте «старую» партицию и вызовите обслуживание —
> она удалится (партиции старше 90 дней не нужны: лимиту хватает 30 дней, аудиту — 90).
> ```sql
> CREATE TABLE alerting.t_dispatch_history_p20260105
>   PARTITION OF alerting.t_dispatch_history FOR VALUES FROM ('2026-01-05') TO ('2026-01-12');
> SELECT alerting.maint_dispatch_partitions(90);   -- p20260105 пропадёт
> ```

---

## 9. Восстановление после сбоя (НФТ-3)

Симулируем падение движка между «пометили запуск running» и «создали задачу»:
вставим запуск со статусом `running` и прошедшим `started_at`, затем перезапустим
движок — он должен **дозавершить** запуск без дублей.

```sql
-- чистим историю, чтобы recovery было видно по факту рассылки (иначе бы сработал cap)
DELETE FROM alerting.t_dispatch_history;

-- «прерванный» запуск (started_at старше recovery-grace = 300 c)
INSERT INTO alerting.t_runs(rule_id, status, started_at, is_dry_run)
SELECT id, 'running', (now() AT TIME ZONE 'utc') - interval '10 minutes', FALSE
FROM alerting.t_rules WHERE code='winback_active_user'
RETURNING id;     -- запомните run_id
```

```bash
docker restart movies-alerting-engine
sleep 8
docker compose logs movies-alerting-engine | grep recover   # "recovering interrupted run"
```

```sql
-- тот же run_id: running → success, dispatched=20
SELECT status, matched_users, dispatched_users FROM alerting.t_runs WHERE id = '<run_id>';
SELECT count(*) FROM alerting.t_dispatch_history;            -- снова 20
```

> Атомарность фазы рассылки гарантирует: статус `running` ⟺ ничего не
> закоммичено, поэтому повтор с тем же `run_id` безопасен. Идемпотентный ключ
> `alerting:{rule_id}:{run_id}` в `adm_create_task` — вторая страховка: даже
> двойное восстановление не даст второго письма.

---

## 10. Дополнительные сценарии

Тот же конвейер, другие витрины/правила (полные SQL — `alerting-service/examples.sql`,
бизнес-истории — `diploma_tz.md` §10):

```bash
# Тренд в сегменте: всплеск просмотров фильма X сегментом women_25-34
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario segment_trend --segment female_25-34_RU --count 30
# Выходной всплеск: события только в субботу-воскресенье прошлой недели
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario weekend_burst --count 30
```
После каждого — refresh соответствующих MV (`mv_segment_film_activity` /
`mv_weekend_film_activity`, см. §3) и регистрация правила из `examples.sql`.

---

## 11. BI поверх витрин (браузер, Superset http://localhost:8088)

Войти `admin`/`admin` → **SQL Lab** → датасорс StarRocks → выполнить:
```sql
SELECT * FROM ugc_analytics.mv_user_activity LIMIT 50;
```
Superset читает те же Materialized views по MySQL-протоколу (датасорс
`starrocks+pymysql://alert_reader@movies-starrocks:9030/default_catalog.ugc_analytics`).

---

## Сброс перед повторным показом

```sql
SELECT alerting.adm_delete_rule('winback_active_user');   -- мягкое удаление
```
Mailpit чистится кнопкой «Delete all». `seed-users`/`trigger-events` идемпотентны —
можно прогнать §2–§9 заново. Полный сброс — `docker compose down -v && up --build`.

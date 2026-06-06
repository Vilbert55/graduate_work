# Демонстрация дипломной части (alerting-service)

Замкнутый контур: событие пользователя -> аналитическое хранилище -> SQL-правило ->
письмо -> клик по ссылке -> событие обратно в хранилище -> воронка отклика.
Правилами управляют SQL-функциями в Postgres, аудиторию выбирают в StarRocks,
письма доставляет существующий `notifications-service`.

Подробный вариант с пояснениями — `cheatsheets/demo_full.md`. Готовые запросы —
`alerting-service/examples.sql`.

## Контур

```
trigger-events -> Kafka -> Routine Load -> user_events (StarRocks)
  -> REFRESH mv_* -> adm_create_rule -> dry-run -> adm_trigger_rule
  -> frequency cap -> t_dispatch_history -> notifications.adm_create_task (per-user context)
  -> RabbitMQ -> email-sender -> Mailpit
  -> клик по ссылке -> GET /ugc/email/click -> recommendation -> Kafka -> user_events
  -> dispatch_log -> mv_rule_conversion -> воронка «отправлено -> перешли по ссылке» (Superset)
```

## Доступы

DBeaver:

| Подключение | Драйвер | Хост:порт | БД | Логин / пароль |
|---|---|---|---|---|
| `movies-pg` | PostgreSQL | `localhost:5438` | `movies` | `postgres` / `POSTGRES_PASSWORD` из `.env` |
| `starrocks-reader` | MySQL | `localhost:9030` | `ugc_analytics` | `alert_reader` / `alert_reader` |
| `starrocks-root` | MySQL | `localhost:9030` | `ugc_analytics` | `root` / *(пусто)* |

Браузер: Mailpit `http://localhost:8025`, Superset `http://localhost:8088`
(`admin`/`admin`), Kafka UI `http://localhost:8081`.

---

## 0. Поднять стек

```bash
docker compose up -d --build      # StarRocks стартует ~1–2 мин
```

## 1. Демо-данные

```bash
docker compose --profile demo run --rm movies-demo-tools seed-users --count 50
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario winback --count 30
```

Показывает: 50 демо-юзеров в `auth.users`, поток `view`-событий в Kafka (топик
`views` в Kafka UI) -> `user_events` в StarRocks через Routine Load.

## 2. Обновить витрины StarRocks (`starrocks-root`)

В демо не ждём часовой `SUBMIT TASK` — синхронизируем вручную (полный блок —
`examples.sql` §7):

```sql
USE ugc_analytics;
INSERT OVERWRITE dim_users
SELECT CAST(u.id AS VARCHAR(36)), u.gender, u.age, u.country,
       concat_ws('_', coalesce(u.gender,'X'),
           CASE WHEN u.age IS NULL THEN 'X' WHEN u.age<18 THEN '0-17'
                WHEN u.age<=24 THEN '18-24' WHEN u.age<=34 THEN '25-34'
                WHEN u.age<=44 THEN '35-44' WHEN u.age<=54 THEN '45-54'
                ELSE '55+' END, coalesce(u.country,'X')),
       u.created_at, u.is_demo
FROM pg_catalog.auth.users u;
REFRESH MATERIALIZED VIEW mv_user_activity   WITH SYNC MODE;
REFRESH MATERIALIZED VIEW mv_user_top_genres WITH SYNC MODE;
```

## 3. Зарегистрировать правило (`movies-pg`)

SQL правила обязан вернуть `user_id` и опционально `context` (JSON для подстановки
в письмо). Полный текст — `examples.sql` §1.

```sql
SELECT alerting.adm_create_rule(
    p_code          := 'winback_active_user',
    p_description   := 'Возврат угасших активных зрителей',
    p_sql           := $sql$
        SELECT user_id, to_json(named_struct('top_genres', t.top_genres)) AS context
        FROM ugc_analytics.mv_user_activity a
        JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
        WHERE a.was_active_last_month = TRUE
          AND a.last_watch_at < now() - INTERVAL 7 DAY
        $sql$,
    p_cron          := '0 9 * * *',
    p_template_code := 'winback_recommendation',
    p_channel       := 'email',
    p_frequency_cap := '{"per_rule_per_user_days": 30}'::jsonb
);
SELECT alerting.adm_enable_rule('winback_active_user');
```

Валидация (ФТ-1, НФТ-2) — осмысленная ошибка на некорректном входе:

```sql
SELECT alerting.adm_create_rule('x','x','DELETE FROM t','0 9 * * *',
        'winback_recommendation','email');   -- invalid_sql: must start with SELECT or WITH
```

Показывает: правило создаётся одной функцией; вход валидируется.

## 4. Тестовый прогон — dry-run (ФТ-5)

```sql
SELECT alerting.adm_dry_run_rule('winback_active_user');
SELECT status, matched_users, after_cap_users, dispatched_users, is_dry_run
FROM alerting.v_runs ORDER BY started_at DESC LIMIT 1;
-- success, 20, 20, 0, is_dry_run=t
```

Показывает: SQL реально выполнен в StarRocks, аудитория посчитана до и после
лимита, писем нет.

## 5. Боевой запуск и per-user context (ФТ-2, ФТ-6/7)

```sql
SELECT alerting.adm_trigger_rule('winback_active_user');
SELECT status, matched_users, after_cap_users, dispatched_users
FROM alerting.v_runs WHERE is_dry_run=FALSE ORDER BY started_at DESC LIMIT 1;
-- success, 20, 20, 20
```

Mailpit: 20 писем. Открыть 2–3 — строка с жанрами у каждого своя (его top-3 из
`context`).

Показывает: правило срабатывает и доставляет письма; в каждом письме — личные
данные пользователя.

## 6. Лимит уведомлений (ФТ-3)

```sql
SELECT alerting.adm_trigger_rule('winback_active_user');
SELECT matched_users, after_cap_users, dispatched_users
FROM alerting.v_runs WHERE is_dry_run=FALSE ORDER BY started_at DESC LIMIT 1;
-- 20, 0, 0
```

Mailpit: новых писем нет.

Показывает: сработал `per_rule_per_user_days=30` — повторно те же пользователи
письмо не получают.

## 7. Замыкание петли — переход по ссылке из письма

В каждом письме персональная ссылка `GET /ugc/email/click`. Клик публикует событие
`recommendation` (`action=clicked`) в Kafka -> `user_events`. Журнал отправок
копируется в StarRocks (`dispatch_log`), витрина `mv_rule_conversion` строит воронку.

Шаг 1 — пустая воронка (`starrocks-root`):

```sql
USE ugc_analytics;
INSERT OVERWRITE dispatch_log
SELECT r.code, CAST(d.user_id AS VARCHAR(36)), d.sent_at, d.channel
FROM pg_catalog.alerting.t_dispatch_history d
JOIN pg_catalog.alerting.t_rules r ON r.id = d.rule_id;
REFRESH MATERIALIZED VIEW mv_rule_conversion WITH SYNC MODE;
```

В Superset (SQL Lab -> Funnel Chart, database `starrocks_analytics`):

```sql
SELECT 'отправлено' AS stage, sent_users AS users
FROM ugc_analytics.mv_rule_conversion WHERE rule_code='winback_active_user'
UNION ALL
SELECT 'перешли по ссылке', clicked_users
FROM ugc_analytics.mv_rule_conversion WHERE rule_code='winback_active_user';
```

Шаг 2 — в Mailpit открыть несколько писем и нажать ссылку «Открыть подборку».

Шаг 3 — пересчитать витрину и нажать RUN на чарте:

```sql
REFRESH MATERIALIZED VIEW mv_rule_conversion WITH SYNC MODE;
```

Показывает: контур замкнулся — виден реальный отклик на письма. Повторный клик по
той же ссылке дубля не создаёт (`request_id = uuid5(rule, run, user)`).

## 8. Надёжность (рассказать словами)

- **История и партиции (ФТ-8).** `alerting.t_dispatch_history` партиционирована по
  неделям; `alerting.maint_dispatch_partitions(N)` нарезает текущую и следующую
  неделю и дропает старше retention. Это основа лимита и журнал для аудита.
- **Восстановление после сбоя (НФТ-3).** Срабатывание идёт тремя фазами; запись
  истории, создание задачи и финализация — в одной транзакции. Пока запуск
  `running`, по нему ничего не закоммичено: при старте движок дозавершает такие
  запуски с тем же `run_id`, дублей нет.

---

## Сброс перед повторным показом

```sql
SELECT alerting.adm_delete_rule('winback_active_user');   -- мягкое удаление
```

Mailpit — «Delete all». `seed-users` / `trigger-events` идемпотентны, повторный
клик по ссылке дубля не создаёт. Полный сброс стенда — `docker compose down -v`
и `up --build` (для demo-tools — `--profile demo build`).

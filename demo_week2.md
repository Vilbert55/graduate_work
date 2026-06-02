# Демонстрация end-to-end (неделя 2)

Пошаговый сценарий ручной демонстрации замкнутого контура alerting-service.
Инструменты: **терминал**, **DBeaver**, **браузер**, **Postman** (последний — опциональный шаг 9).

Контур, который показываем:
```
seed-users → trigger-events → Kafka → Routine Load → user_events
   → REFRESH mv_* → adm_create_rule → adm_trigger_rule
   → notifications.adm_create_task → RabbitMQ → email-sender → Mailpit
```

---

## 0. Доступы (что куда подключать)

| Что | Адрес | Логин / пароль |
|---|---|---|
| Postgres (схемы `alerting`, `notifications`, `auth`) | `localhost:5438`, БД `movies` | `postgres` / *(POSTGRES_PASSWORD из `.env`)* |
| StarRocks — аналитик (только SELECT) | MySQL-драйвер, `localhost:9030`, БД `ugc_analytics` | `alert_reader` / `alert_reader` |
| StarRocks — админ (REFRESH/INSERT OVERWRITE) | `localhost:9030` | `root` / *(пусто)* |
| Mailpit (приёмник писем) | http://localhost:8025 | — |
| Superset (BI) | http://localhost:8088 | `admin` / `admin` |
| Kafka UI (посмотреть поток событий) | http://localhost:8081 | — |

> Порт Postgres берётся из `EXTERNAL_DB_PORT` в `.env` (по умолчанию `5438`).

**DBeaver:** заведи два соединения — PostgreSQL (`localhost:5438`) и MySQL (`localhost:9030`, база `ugc_analytics`). Шпаргалка аналитика с готовыми запросами — `alerting-service/examples.sql`.

---

## 1. Проверка, что стек поднят (терминал)

```bash
cd ~/praktikum/graduate_work

# Все init/migrations завершились с кодом 0?
# (фильтруем по колонке имени — иначе grep ловит подстроку "init"
#  в команде запуска movies-superset и даёт ложную тревогу)
docker compose ps -a --format '{{.Name}}\t{{.Status}}' \
  | grep -E '^[^[:space:]]*(init|migrations)' | grep -v 'Exited (0)' \
  && echo "ВНИМАНИЕ: что-то упало" || echo "OK: все init-контейнеры отработали"

# Routine Load жив (4 потока в RUNNING)?
docker exec movies-starrocks mysql -uroot -P9030 -h127.0.0.1 -e \
  "USE ugc_analytics; SHOW ROUTINE LOAD;" | awk '{print $2, $9}'
```

---

## 2. Засеять демо-пользователей (терминал)

```bash
docker compose --profile demo run --rm movies-demo-tools seed-users --count 50
```
Создаёт 50 юзеров в `auth.users` с `is_demo=TRUE`, заполненными `gender/age/country` и `email = <login>@demo.local`. Идемпотентно (повтор удалит прошлых демо-юзеров).


---

## 3. Сгенерировать события по сценарию win-back (терминал)

```bash
docker compose --profile demo run --rm movies-demo-tools \
  trigger-events --scenario winback --count 30
```
Каждому демо-юзеру шлёт в Kafka 10–15 `view`-событий с датами «30…8 дней назад» и тишину последние 7 дней — это и есть паттерн «был активен, перестал смотреть».

**Проверка (браузер, Kafka UI http://localhost:8081):** топик `views` — видно прирост сообщений. Routine Load стримит их в StarRocks.

**Проверка (DBeaver, StarRocks под `alert_reader`):**
```sql
SELECT count(*) FROM ugc_analytics.user_events;   -- выросло (сотни событий)
```

---

## 4. Обновить витрины (DBeaver, StarRocks под `root`)

В демо не ждём часовой `SUBMIT TASK` — синхронизируем вручную. Блок целиком есть
в `alerting-service/examples.sql` §7.

```sql
USE ugc_analytics;
-- dim_users — подтянуть свежих демо-юзеров из Postgres
-- (segment_code: возрастная полоса выводится из целочисленного u.age)
INSERT OVERWRITE dim_users
SELECT CAST(u.id AS VARCHAR(36)), u.gender, u.age, u.country,
       concat_ws('_', coalesce(u.gender,'X'),
           CASE WHEN u.age IS NULL THEN 'X'
                WHEN u.age < 18  THEN '0-17'  WHEN u.age <= 24 THEN '18-24'
                WHEN u.age <= 34 THEN '25-34' WHEN u.age <= 44 THEN '35-44'
                WHEN u.age <= 54 THEN '45-54' ELSE '55+' END,
           coalesce(u.country,'X')),
       u.created_at, u.is_demo
FROM pg_catalog.auth.users u;

-- Пересчитать витрины win-back
REFRESH MATERIALIZED VIEW mv_user_activity   WITH SYNC MODE;
REFRESH MATERIALIZED VIEW mv_user_top_genres WITH SYNC MODE;
```

**Проверка (под `alert_reader`):**
```sql
SELECT count(*) FROM ugc_analytics.mv_user_activity WHERE was_active_last_month = TRUE; -- >0
```

---

## 5. Зарегистрировать правило (DBeaver, Postgres)

Из `alerting-service/examples.sql` §2:
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
```
> Показать защиту валидации: попробуй `p_channel := 'telegram'` → ошибка `invalid_channel`; `p_cron := 'кривой'` → `invalid_cron`.

---

## 6. Тестовый прогон без рассылки — dry-run (DBeaver, Postgres)

```sql
SELECT alerting.adm_dry_run_rule(
    (SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));
-- через 1-2 сек:
SELECT status, matched_users, after_cap_users, dispatched_users, error
FROM alerting.v_runs ORDER BY started_at DESC LIMIT 1;
```
Ожидаем: `status=success`, `matched_users>0`, **`dispatched_users=0`** (письма НЕ ушли).

> Видно что здесь: `adm_dry_run_rule` шлёт `pg_notify`, движок (контейнер `movies-alerting-engine`) подхватывает, выполняет SQL в StarRocks, но `adm_create_task` не зовёт.

---

## 7. Боевой запуск — рассылка (DBeaver, Postgres)

```sql
SELECT alerting.adm_trigger_rule(
    (SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));
-- через 1-2 сек:
SELECT status, matched_users, dispatched_users, duration_ms, notification_task_id
FROM alerting.v_runs ORDER BY started_at DESC LIMIT 1;
```
Ожидаем: `status=success`, `dispatched_users = matched_users`, заполнен `notification_task_id`.

**Проверка задачи в notifications (Postgres)** — задача fan-out'нулась в сообщения и они ушли:
```sql
SELECT m.status, count(*)
FROM notifications.t_messages m
WHERE m.task_id = (SELECT id FROM notifications.t_tasks ORDER BY created_at DESC LIMIT 1)
GROUP BY m.status;
```
Ожидаем `status=sent` с числом = `dispatched_users`. Если строк нет / `inserted=0` в
логах scheduler — почти всегда рассинхрон шаблона: тело письма дёргает переменную,
которой нет в namespace (доступны только `user` и `params`).

---

## 8. Письма дошли (браузер, Mailpit http://localhost:8025)

Открыть Mailpit — в инбоксе письма с темой вида **«<Имя>, мы соскучились!»**, адресатам
`<login>@demo.local`. Открыть письмо — тело собрано из шаблона `winback_recommendation`
(Jinja, StrictUndefined; жанры пока по дефолту шаблона — см. неделя 3 / ФТ-2).

> Контрольная точка демо: число писем = `dispatched_users` из шага 7.

---

## 9. (Опционально) Замыкание контура — реакция на письмо (Postman)

Показывает интеграционную доработку недели 2 — новый `event_type=recommendation`
в activity-tracker (контур «письмо → клик → факт обратно в StarRocks»).

**9.1 Получить токен** — `POST http://localhost:8002/auth/login`
Body (JSON): `{"login": "<любой demo-login из шага 2>", "password": "demo_password"}`
→ из ответа скопировать `access_token`.

**9.2 Отправить реакцию** — `POST http://localhost/ugc/api/v1/events/recommendation`
Header: `Authorization: Bearer <access_token>`
Body (JSON):
```json
{
  "rule_code": "winback_active_user",
  "notification_message_id": "<id из notifications.t_messages>",
  "action": "clicked",
  "film_id": null
}
```
→ событие уходит в Kafka-топик `recommendations`, Routine Load `recommendations_load`
кладёт его в `user_events` с `event_type='recommendation'`. Проверка в StarRocks:
```sql
SELECT count(*) FROM ugc_analytics.user_events WHERE event_type='recommendation';
```

---

## 10. BI поверх витрин (браузер, Superset http://localhost:8088)

Войти `admin`/`admin` → **SQL Lab** → датасорс StarRocks → выполнить:
```sql
SELECT * FROM ugc_analytics.mv_user_activity LIMIT 50;
```
Показать, что Superset читает те же Materialized views по MySQL-протоколу (датасорс
`starrocks+pymysql://alert_reader@movies-starrocks:9030/default_catalog.ugc_analytics`).

---

## Сброс перед повторным показом

```sql
-- Postgres: удалить демо-правило
SELECT alerting.adm_delete_rule((SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));
```
Mailpit чистится кнопкой «Delete all». `seed-users`/`trigger-events` идемпотентны —
можно просто прогнать шаги 2–8 заново. Полный сброс — `docker compose down -v && up --build`.

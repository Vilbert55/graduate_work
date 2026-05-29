# Дипломный проект — Event-driven alerting service для онлайн-кинотеатра

Диаграммы: 
- `diploma_architecture.drawio` схема дипломной части
- `diploma_architecture_full.drawio` весь проект
---

## 1. О проекте

Новый сервис `alerting-service` подключается к уже работающему конвейеру `activity-tracker -> Kafka -> StarRocks` (сбор пользовательских действий). Поверх событий и измерений в StarRocks он позволяет аналитику декларативно задавать SQL-правила вида «когда метрика X удовлетворяет условию Y — отправить уведомление по шаблону Z аудитории, которую вернул запрос». Срабатывание правил — автоматически по расписанию. Лимит уведомлений гарантирует, что пользователь не получит больше N сообщений в сутки. Результат — замкнутый контур от пользовательских событий до доставленного письма, без участия маркетолога-оператора.

---

## 2. Идея модуля и бизнес-ценность

### 2.1 Проблема

В стриминговых сервисах между «аналитик увидел паттерн на дашборде» и «пользователь получил релевантное письмо» лежит длинная ручная цепочка: аналитик -> постановщик задач в маркетинг -> копирайтер -> менеджер кампаний в CRM-системе -> запуск рассылки. Цикл — часы или дни. Часть сценариев требуют реакции в течение часов; такой темп достижим только при автоматизации.

### 2.2 Решение

Замкнутый событийный контур:

```
события пользователей -> аналитическое хранилище -> SQL-правило -> аудитория -> уведомление
```

Аналитик один раз описывает правило (SQL-запрос, расписание, шаблон уведомления, лимиты), и оно срабатывает автономно.

### 2.3 Примеры сценариев, в которых пригодится автоматическая реакция:

- **Возврат пользователя (win-back).** Активный пользователь (≥3 просмотра в неделю в последний месяц) не смотрел ничего 7+ дней -> персональная подборка фильмов в его top-жанрах.
- **Реакция на провальный релиз.** Доля бросивших просмотр новой премьеры (drop-off) >70% на 15-й минуте -> пользователям, бросившим просмотр, рекомендация альтернативы того же жанра.
- **Тренд в сегменте -> кросс-промо.** Сегмент аудитории внезапно активно смотрит фильм X -> рассылка тому же сегменту про похожий новый релиз.

### 2.4 Готовые аналоги

Mindbox, Sendsay, RetentionRocket (Россия), Customer.io, Braze, Klaviyo, Bloomreach (зарубежные). Класс продуктов — автоматические рассылки по поведению пользователей.

### 2.5 Чем новый сервис отличается от готовых решений

Перечисленные системы заточены под маркетолога без SQL: визуальные конструкторы условий, готовые сегменты, рекомендательные модели.
Целевая аудитория диплома — продуктовый аналитик с уверенным SQL. Это упрощает интерфейс (визуальный конструктор не нужен) и одновременно даёт аналитику максимум гибкости — любая бизнес-логика выражается одним `SELECT`.

---

## 3. Целевой пользователь

**Продуктовый/маркетинговый аналитик кинотеатра.** 

**Рабочий процесс:**
1. В DBeaver подключается к StarRocks, пишет `SELECT` по `mv_*` и `dim_*`, убеждается, что выборка возвращает нужных пользователей.
2. Вызывает `alerting.adm_create_rule(...)`, передавая тот же SQL.
3. Делает тестовый прогон через `adm_dry_run_rule` — видит, сколько пользователей попадёт в выборку и сколько останется после лимита уведомлений.
4. Включает правило: `adm_enable_rule`.
5. Следит за работой через представления `v_runs` и `v_dispatch`.

---

## 4. Функциональные требования

| № | Требование |
|---|---|
| ФТ-1  | Аналитик создаёт правило одной SQL-функцией `alerting.adm_create_rule(...)`. Параметры — текст SQL-запроса, расписание, шаблон уведомления, канал доставки, лимиты. Все параметры валидируются. |
| ФТ-2  | SQL правила обязан возвращать колонку `user_id` и опционально `context` (JSON с данными для подстановки в шаблон). |
| ФТ-3  | Двухуровневый лимит уведомлений: минимальный интервал между сообщениями от одного правила одному пользователю + общий потолок сообщений на пользователя в сутки. |
| ФТ-4  | Управление правилом: обновление, включение/выключение, мягкое удаление. |
| ФТ-5  | Тестовый прогон правила — выполнить SQL без рассылки и вернуть размер аудитории до и после применения лимита, плюс несколько `user_id` для проверки. |
| ФТ-6  | Ручной запуск правила вне расписания. |
| ФТ-7  | Движок по расписанию каждого активного правила выполняет его SQL в StarRocks, применяет лимит уведомлений и создаёт одну задачу в `notifications-service`. Каждое срабатывание идемпотентно: повтор после сбоя не создаёт дублей. |
| ФТ-8  | Представления для аудита: список правил со статусом, история срабатываний, история отправок (для разбора жалоб). |
| ФТ-9  | Materialized views в StarRocks — по одному на каждый ключевой сценарий плюс один общий. Обновляются StarRocks автоматически. |
| ФТ-10 | Таблицы измерений (`dim_films`, `dim_users`, `dim_genres`) синхронизируются раз в час из Postgres в StarRocks средствами самого StarRocks. Отдельного ETL-сервиса не требуется. |
| ФТ-11 | BI-дашборды (2–3 чарта) поверх Materialized views в Apache Superset. |
| ФТ-12 | `notifications-service` не модифицируется — используются только его публичные SQL-функции (`adm_create_task`, `adm_upsert_template`). |

---

## 5. Нефункциональные требования

| № | Требование |
|---|---|
| НФТ-1 | **Производительность.** SQL-функции управления отвечают за 300 мс (p99). Задержка от события пользователя до задачи в `notifications-service` — не более 5 минут. |
| НФТ-2 | **Предсказуемые ошибки.** Все входные параметры валидируются. Бизнес-ошибки возвращаются с понятным кодом (`template_not_found`, `invalid_cron`, ...). Коды 5xx — только при инфра-сбоях. |
| НФТ-3 | **Надёжность.** Перезапуск движка после сбоя не приводит к дублям уведомлений и не теряет результатов прерванного срабатывания. |
| НФТ-4 | **Минимальные права.** Движок ходит в StarRocks с правом только на чтение аналитической схемы. Аналитик в Postgres имеет право только вызова SQL-функций схемы `alerting`, без прямого доступа к таблицам. |
| НФТ-5 | **Наблюдаемость.** Структурированные логи в ELK, ошибки в Glitchtip, базовые счётчики (количество запусков, ошибок, отправленных уведомлений). |
| НФТ-6 | **Тесты.** Юнит-тесты бизнес-логики движка (лимит, разбор контракта колонок, обработка ошибок SQL) + сквозной тест «создание правила -> ручной запуск -> письмо в Mailpit». |

---

## 6. Архитектура


### 6.1 Существующие компоненты (используются, не модифицируются)

| Компонент | Роль для проекта |
|---|---|
| `movies-activity-tracker-service` | Принимает события клика/просмотра, валидирует, отправляет в Kafka. |
| `movies-kafka` | Транспорт событий пользователей. |
| `movies-starrocks` + Routine Load | Стримит события из Kafka в таблицу `ugc_analytics.user_events`. |
| `movies-db` (Postgres) | Источник измерений (фильмы, пользователи, жанры). Также хост схемы `alerting`. |
| `movies-notifications-*` (весь стек) | Доставка уведомлений. Alerting только вызывает `notifications.adm_create_task(...)`. |
| `movies-admin-panel-service` | Django-админка. Опционально — простая страница для просмотра `v_rules` / `v_runs`. |
| `movies-mailpit` | Локальный SMTP-приёмник. |

### 6.2 Новые компоненты

| Компонент | Роль |
|---|---|
| `movies-alerting-migrations` | Init-контейнер: миграции схемы `alerting` в Postgres + создание SQL-функций, представлений, ролей. |
| `movies-starrocks-dims-init` | Init-контейнер: создаёт `dim_films`, `dim_users`, `dim_genres` и Materialized views, регистрирует JDBC Catalog на Postgres и запускает `SUBMIT TASK` для часовой синхронизации измерений. |
| `movies-alerting-engine` | Основной воркер: планировщик APScheduler, выполнение SQL-правил, проверка лимита уведомлений, создание задач в `notifications-service`, восстановление после сбоя. Отдельного HTTP-API нет — управление через SQL. |
| `movies-superset` | Apache Superset с готовой конфигурацией подключения к StarRocks. |
| `movies-superset-init` | Init-контейнер: загружает 2–3 готовых дашборда поверх Materialized views. |

### 6.3 Поток данных

**Приём пользовательских событий (уже работает).** Пользователь -> `activity-tracker` -> Kafka -> StarRocks. Таблица `user_events` пополняется потоково через Routine Load.

**Подготовка измерений и витрин (новое).** Раз в час StarRocks собственным планировщиком перезаливает таблицы `dim_films / dim_users / dim_genres` из Postgres через JDBC Catalog. Materialized views поверх `user_events` и `dim_*` пересчитываются StarRocks асинхронно по факту изменения источников.

**Жизненный цикл правила (аналитик).** Аналитик в DBeaver вызывает `alerting.adm_create_rule(...)` — правило ложится в таблицу `t_rules`.

**Срабатывание правила (новое).** Планировщик движка по расписанию каждого активного правила выполняет его SQL в StarRocks, получает аудиторию, отсекает пользователей, попавших под лимит уведомлений, и одной транзакцией пишет историю отправок и создаёт задачу в `notifications-service`. Идемпотентный ключ задачи защищает от дублей при повторе после сбоя.

**Доставка (уже работает).** `notifications-service` разворачивает задачу в сообщения, кладёт в RabbitMQ — отправитель писем доставляет в Mailpit.

**Визуализация.** Superset по MySQL-протоколу читает Materialized views и строит дашборды.

### 6.4 Изменения в существующих сервисах для интеграции

| Сервис | Что меняется |
|---|---|
| **auth-service** | Alembic-миграция в `auth.users`: добавляем nullable-колонки `gender VARCHAR(16)`, `age_group VARCHAR(16)`, `country VARCHAR(2)`, `is_demo BOOLEAN DEFAULT FALSE`. Pydantic-схемы профиля (`/me`, регистрация) расширяются соответствующими полями (`is_demo` — только для внутреннего использования). |
| **activity-tracker-service** | Новый эндпоинт `POST /ugc/api/v1/events/recommendation` принимает реакции пользователя на письма alerting (поля `rule_code`, `notification_message_id`, `action ∈ {opened, clicked, dismissed}`, опц. `film_id`). Новый Kafka-топик `recommendations`. Замыкает контур «правило → задача → письмо → клик → факт обратно в StarRocks» — аналитик в Superset может построить чарт конверсии собственного правила. |
| **starrocks_init/init.sql** | Таблица `user_events` переведена с `DUPLICATE KEY(request_id, user_id, event_type)` на **`PRIMARY KEY (request_id, event_type)`** — встроенная дедупликация StarRocks (REPLACE-семантика при конфликте PK). Добавлена Routine Load `recommendations_load` для нового event_type. Добавлены колонки `rule_code`, `notification_message_id`, `action`. |


### 6.5 Логическое разделение ответственностей

| Аспект | Кто отвечает |
|---|---|
| Когда что-то проверять | alerting (расписание в каждом правиле) |
| Кого затрагивает уведомление | alerting (SQL правила вычисляет аудиторию динамически) |
| Что отправить | notifications (шаблоны хранятся и подставляются там) |
| Как доставить | notifications (очередь исходящих + RabbitMQ + отправители) |
| Сколько раз можно отправить пользователю | alerting (лимит уведомлений) |
| Идемпотентность каждого срабатывания | alerting (формирует ключ) -> notifications (использует его) |

Тонкий момент: `notifications-service` в текущем виде умеет работать по расписанию, но раскрывает аудиторию в момент срабатывания. Поэтому alerting не пользуется этим — он каждый раз создаёт одноразовую задачу с уже посчитанной аудиторией.

---

## 7. Технический стек с обоснованием

| Компонент | Выбор | Обоснование |
|---|---|---|
| Язык | Python 3.12 | Требование ТЗ диплома; единый стек проекта. |
| Планировщик | APScheduler | Лёгкий, работает в том же процессе, поддерживает cron-выражения. Celery был бы избыточен — у нас нет распределённой очереди, она уже есть в `notifications-service`. |
| ORM и миграции | SQLAlchemy 2.0 + Alembic | Соответствует `notifications-service`, `auth-service`, `community-content-service`. |
| Драйвер Postgres | `psycopg[binary]` или `asyncpg` | Согласовано с остальным проектом. |
| Драйвер StarRocks | `aiomysql` / `PyMySQL` | StarRocks общается по MySQL-протоколу. |
| BI | Apache Superset 4.x | Open-source, есть MySQL-коннектор, лучше Metabase работает на больших аналитических объёмах. |
| Синхронизация dim-таблиц | StarRocks JDBC Catalog + `SUBMIT TASK ... SCHEDULE` | Нативный механизм StarRocks для пакетной загрузки из внешних БД — парный к Routine Load (та же логика «оркестрация внутри StarRocks», но для batch). Отдельный Python-сервис (как `films-etl-service` для Elasticsearch) был бы оправдан при CDC или сложных преобразованиях; для трёх таблиц с полной перезаливкой раз в час это избыточно. |
| Логи и ошибки | Структурированные JSON-логи в ELK, ошибки в Glitchtip | Уже развёрнуто в проекте. |

---

## 8. SQL-API для аналитика

Стиль вызова — как в `notifications.adm_*`: `SECURITY DEFINER`-функции с понятными именами, JSONB для гибких параметров, `RAISE EXCEPTION` с осмысленным кодом ошибки, права через GRANT EXECUTE на роль `alerting_admin`.

### 8.1 Полный список функций

| Функция | Назначение |
|---|---|
| `adm_create_rule(p_code, p_description, p_sql, p_cron, p_template_code, p_channel, p_frequency_cap, p_max_users, p_idempotency_key, p_created_by) -> UUID` | Создать правило. Идемпотентна. |
| `adm_update_rule(p_rule_id, p_sql, p_cron, p_template_code, ...)` | Обновить (`NULL` = не менять). |
| `adm_enable_rule(p_rule_id)` / `adm_disable_rule(p_rule_id)` | Переключатели. |
| `adm_delete_rule(p_rule_id)` | Мягкое удаление: `is_deleted = true`. |
| `adm_dry_run_rule(p_rule_id) -> table(matched int, after_cap int, sample uuid[])` | Тестовый прогон без рассылки. |
| `adm_trigger_rule(p_rule_id) -> UUID (run_id)` | Ручной запуск сейчас вне расписания. |

### 8.2 Представления

| Представление | Содержимое |
|---|---|
| `v_rules` | `id`, `code`, статус (`active`/`disabled`/`invalid`/`deleted`), расписание, `template_code`, время последнего и следующего запуска, число отправок за 24 часа. |
| `v_runs` | `rule_id`, `code`, время старта, длительность в мс, размер выборки, число после лимита, число отправленных, статус, ошибка. |
| `v_dispatch` | `rule_id`, `code`, `user_id`, канал, время отправки — для разбора жалоб. |

### 8.3 Пример цикла работы аналитика (сжато)

Полные примеры с SQL-выборками и шаблонами вынесены в `alerting-service/examples.sql`. Краткий цикл (правило возврата угасшего пользователя):

```sql
-- 1. Тестируем выборку в StarRocks (DBeaver)
SELECT
    a.user_id,
    jsonb_build_object('top_genres', t.top_genres) AS context
FROM ugc_analytics.mv_user_activity a
JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
WHERE a.was_active_last_month = TRUE
  AND a.last_watch_at < now() - INTERVAL 7 DAY;

-- 2. Регистрируем правило в Postgres
SELECT alerting.adm_create_rule(
    p_code := 'winback_active_user',
    p_sql  := $$ <тот же SQL> $$,
    p_cron := '0 9 * * *',
    p_template_code := 'winback_recommendation',
    p_channel := 'email',
    p_frequency_cap := '{"per_rule_per_user_days": 30, "per_user_per_day": 1}'::jsonb
);

-- 3. Dry-run -> 4. Enable -> 5. Опционально trigger -> 6. Мониторинг через v_runs / v_dispatch
SELECT * FROM alerting.adm_dry_run_rule('<rule_id>');
SELECT alerting.adm_enable_rule('<rule_id>');
```

---

## 9. Схема данных

### 9.1 Postgres, схема `alerting`

```sql
CREATE SCHEMA alerting;

-- Правила
CREATE TABLE alerting.t_rules (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code              TEXT NOT NULL UNIQUE,
    description       TEXT,
    sql_query         TEXT NOT NULL,
    cron_expression   TEXT NOT NULL,
    template_code     TEXT NOT NULL,         -- ссылка на notifications.t_templates.code
    channel           TEXT NOT NULL,         -- email | ws
    frequency_cap     JSONB NOT NULL DEFAULT '{}',
    max_users         INTEGER NOT NULL DEFAULT 50000,
    is_enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted        BOOLEAN NOT NULL DEFAULT FALSE,
    status            TEXT NOT NULL DEFAULT 'active',  -- active | invalid
    last_validation_error TEXT,
    next_run_at       TIMESTAMP,
    last_run_at       TIMESTAMP,
    idempotency_key   TEXT UNIQUE,
    created_by        TEXT NOT NULL DEFAULT 'admin',
    created_at        TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    updated_at        TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);
CREATE INDEX ON alerting.t_rules (is_enabled, is_deleted, next_run_at);

-- История запусков
CREATE TABLE alerting.t_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id           UUID NOT NULL REFERENCES alerting.t_rules(id),
    started_at        TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    finished_at       TIMESTAMP,
    duration_ms       INTEGER,
    matched_users     INTEGER,
    after_cap_users   INTEGER,
    dispatched_users  INTEGER,
    notification_task_id UUID,                -- ссылка на notifications.t_tasks.id
    status            TEXT NOT NULL,          -- running | success | failed | skipped
    error             TEXT
);
CREATE INDEX ON alerting.t_runs (rule_id, started_at DESC);

-- История доставки (для лимита уведомлений и аудита)
CREATE TABLE alerting.t_dispatch_history (
    id                BIGSERIAL,
    rule_id           UUID NOT NULL,
    user_id           UUID NOT NULL,
    channel           TEXT NOT NULL,
    sent_at           TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
    PRIMARY KEY (id, sent_at)
) PARTITION BY RANGE (sent_at);
-- партиции по неделям, создание автоматическое через pg_partman или скрипт
CREATE INDEX ON alerting.t_dispatch_history (user_id, sent_at DESC);
CREATE INDEX ON alerting.t_dispatch_history (rule_id, user_id, sent_at DESC);
```

Все adm_-функции — `SECURITY DEFINER`, владелец `postgres`, права через `GRANT EXECUTE ... TO alerting_admin`.

### 9.2 StarRocks, база `ugc_analytics`

Существующее (изменено): `user_events` (наполняется Routine Load). Таблица
переведена с `DUPLICATE KEY` на **`PRIMARY KEY (request_id, event_type)`** —
дедупликация обеспечивается транспортом (REPLACE-семантика StarRocks при
конфликте PK), а не запросами в правилах. Добавлены колонки `rule_code`,
`notification_message_id`, `action` под новый event_type `recommendation`.

Добавляется:

**Dim-таблицы** (синхронизируются раз в час из Postgres через JDBC Catalog + `SUBMIT TASK`):
- `dim_films(film_id PK, title, type, genres ARRAY<STRING>, is_new BOOLEAN, creation_date, rating)` — `is_new` вычисляется по `creation_date > now() - INTERVAL 30 DAY`.
- `dim_users(user_id PK, gender, age_group, country, segment_code, registered_at, is_demo)` — `segment_code` производный (`concat_ws('_', gender, age_group, country)`, напр. `female_25-34_RU`).
- `dim_genres(genre_id PK, name)`
- `dim_date(date PK, year, quarter, month, day, day_of_week, week_of_year, is_weekend, is_holiday)` — задействует ранее неиспользуемый `content.date_dimension` из `admin-panel-service`; синхронизируется одноразовым `SUBMIT TASK sync_dim_date` (растёт ровно на одну строку в сутки). Применяется в правилах вида «по выходным», «по пятницам», «в праздничные дни» через join — без дублирования date-арифметики в каждом SQL.

Все четыре — `PRIMARY KEY` таблицы StarRocks (поддерживают `INSERT OVERWRITE`).

**Materialized views** (5 шт., по числу сценариев + два общих):
- `mv_user_activity` — для сценария возврата угасшего пользователя: `(user_id, watches_last_30d, was_active_last_month BOOLEAN, last_watch_at)`.
- `mv_user_top_genres` — компаньон того же сценария: `(user_id, top_genres ARRAY<STRING>)` (top-3 жанра по числу просмотров за 30 дней).
- `mv_segment_film_activity` — для сценария тренда в сегменте.
- `mv_film_watch_hourly` — общий MV (часовые агрегаты по фильмам), используется и в Superset, и в дополнительных правилах.
- `mv_weekend_film_activity` — пример агрегата с join к `dim_date.is_weekend`. Поддерживает сценарий «фильм X стал популярен на выходных → промо в субботу утром».

Все MV — async, refresh по факту изменения источников (StarRocks делает это автоматически).

---

## 10. Демонстрация

Показать на защите два основных сценария — «возврат угасшего пользователя»
и «тренд в сегменте», плюс дополнительно `weekend_burst` для иллюстрации
применения `dim_date` (см. §10.4).

Канал в демо — только электронная почта (Mailpit как приёмник). WebSocket-канал поддерживается архитектурно.

### 10.1 Инструменты для демонстрации

Для подготовки и оживления сценариев добавляются две Python-утилиты (могут быть подкомандами одного CLI), запускаются вручную перед демо:

- **`demo-seeder`** — создаёт N юзеров в `auth.users` с заполненными `gender / age_group / country` и `is_demo = TRUE`. Фильмы не создаёт — берутся существующие из фикстур `content.film_work`. Идемпотентен: повторный запуск удаляет юзеров с `is_demo = TRUE` и создаёт заново.
- **`event-trigger`** — генерирует события в Kafka только для демо-юзеров, подставляя реальные `film_id` из существующих фильмов (отбор по жанру/рейтингу под сценарий). Параметры (сценарий, окно времени, количество событий) задаются ключами командной строки.

### 10.2 Сценарий A - Возврат пользователя (win-back)

**Бизнес-история.** Пользователь был активен (≥3 просмотра в неделю в последний месяц) и вдруг не смотрит ничего уже 7 дней. -> Утром раз в день он получает письмо с подборкой свежих фильмов в его top-3 жанрах.

**MV `mv_user_activity`:** `(user_id, watches_last_30d, was_active_last_month BOOLEAN, last_watch_at TIMESTAMP)`.
**MV `mv_user_top_genres`:** `(user_id, top_genres ARRAY<STRING>)` — top-3 жанра по числу просмотров за 30 дней.

**Правило:** см. пример в 8.3.

**Cron:** `0 9 * * *` (каждое утро в 9:00 UTC).

**Cap:** не чаще 1 раза в 30 дней по этому правилу, плюс глобальный потолок 1 письмо/день.

**Демо-триггер.** Перед демо `demo-seeder` создаёт N демо-юзеров. `event-trigger` для каждого из них льёт серию `view`-событий с `client_time` в диапазоне «30…8 дней назад» (создаёт паттерн «был активен») и затем тишину последние 7+ дней. Дополнительно льёт несколько событий с известными `film_id` определённых жанров, чтобы `mv_user_top_genres` дал предсказуемый результат. После часового refresh dims/MV (или ручного `EXECUTE TASK`) — тик engine, письма в Mailpit.

### 10.3 Сценарий B - Тренд в сегменте

**Бизнес-история.** Сегмент `women_25_34` за последние 24 часа активно смотрит фильм X (>100 уникальных зрителей при обычном уровне <20). -> Тому же сегменту, кто X ещё не смотрел, приходит рекомендация похожего нового релиза.

**MV `mv_segment_film_activity`:** `(bucket_date DATE, segment VARCHAR, film_id UUID, views_24h BIGINT, viewer_count_24h BIGINT)`.

**Правило:**
```sql
WITH trending AS (
  SELECT segment, film_id, viewer_count_24h
  FROM ugc_analytics.mv_segment_film_activity
  WHERE bucket_date = current_date AND viewer_count_24h > 100
),
already_seen AS (
  SELECT DISTINCT user_id, film_id FROM ugc_analytics.mv_film_watch_hourly
  WHERE bucket_hour > now() - INTERVAL 30 DAY
)
SELECT
  u.user_id,
  jsonb_build_object('trending_film_id', t.film_id, 'segment', t.segment) AS context
FROM ugc_analytics.dim_users u
JOIN trending t ON t.segment = u.segment_code
LEFT JOIN already_seen a ON a.user_id = u.user_id AND a.film_id = t.film_id
WHERE a.user_id IS NULL
```

**Cron:** `0 */6 * * *`.

**Cap:** не чаще 1 раза в 7 дней; глобальный потолок 3 письма/день.

**Демо-триггер.** Перед демо `demo-seeder` создаёт пользователей целевого сегмента (`women_25_34`). `event-trigger` выбирает фильм X из существующих фикстур (по фильтру жанра/рейтинга) и генерирует всплеск просмотров этого фильма от пользователей. После часового refresh dim-таблиц и MV — тик правила, письма пользователям сегмента, которые X ещё не смотрели.

### 10.4 Сценарий C (доп.) — Выходной всплеск (weekend burst)

**Бизнес-история.** Группа пользователей активно смотрит подборку фильмов
именно в субботу-воскресенье. → В пятницу утром им уходит письмо с
подборкой на грядущие выходные.

**MV `mv_weekend_film_activity`:** `(bucket_date DATE, film_id PK, views, unique_viewers)` — агрегат строится с фильтром `dim_date.is_weekend = TRUE`.

**Правило:**
```sql
SELECT
  user_id,
  jsonb_build_object('film_id', m.film_id) AS context
FROM ugc_analytics.mv_weekend_film_activity m
JOIN ugc_analytics.user_events e ON e.film_id = m.film_id
  AND e.event_type = 'view'
  AND e.client_time > now() - INTERVAL 14 DAY
WHERE m.bucket_date > current_date - INTERVAL 14 DAY
GROUP BY user_id, m.film_id
HAVING count(*) >= 3
```

**Cron:** `0 9 * * 5` (каждую пятницу в 9:00 UTC).
**Cap:** не чаще 1 раза в 14 дней.

**Демо-триггер.** `event-trigger --scenario weekend_burst` льёт view-события
демо-юзеров только в субботу-воскресенье прошлой недели. Триггерит
`mv_weekend_film_activity`. Иллюстрирует, как `dim_date` (бывший
неиспользуемый `content.date_dimension`) упрощает date-арифметику в правилах.

---

## 11. Риски

| № | Риск | Решение |
|---|---|---|
| R1 | Задержка обновления Materialized views в StarRocks больше ожидаемой - «почти реального времени» не получается | Запасной вариант: обычные `VIEW` + пакетное обновление по расписанию; либо уменьшение интервала срабатывания правила. |
| R4 | Аналитик пишет SQL, возвращающий миллион `user_id` | Жёсткий потолок размера выборки, правило при превышении уходит в статус `failed` с предупреждением. |
| R5 | Сбой движка между выполнением SQL и созданием задачи -> потенциальный дубль | Идемпотентный ключ `alerting:{rule_id}:{run_id}` в `notifications.adm_create_task`. |
| R6 | Один экземпляр движка - точка отказа | Осознанный компромисс MVP: автоперезапуск контейнера + восстановление прерванных запусков. |
| R7 | Неоптимальный SQL аналитика подвешивает StarRocks | Тайм-аут запроса 30 секунд на уровне сессии, опционально — `EXPLAIN` при первой регистрации правила. |
| R8 | Перекрытие правил - пользователь получает слишком много | Общий потолок «сообщений на пользователя в сутки». |



---

## 12. Возможные улучшения

Эти пункты сознательно вынесены за рамки 4-недельного диплома, но осмыслены и выделены в компромисс.

| Улучшение | Краткое описание |
|---|---|
| **Leader election** | Заменить single-instance engine на N экземпляров с выбором лидера через Postgres advisory lock. Снимает SPOF, не требует внешних координаторов вроде etcd. Каждый воркер при старте пытается взять `pg_try_advisory_lock(<const>)`; владелец лока — активный лидер, остальные ждут наготове. |
| **Retention/TTL для t_dispatch_history** | Сейчас таблица партиционирована по неделям, но партиции не дропаются — данные хранятся бессрочно. При больших объёмах рассылок (миллионы строк/сутки) индексы тяжелеют. Решение — крон-скрипт раз в сутки делает `DROP PARTITION` для партиций старше 90 дней. Лимиту уведомлений нужны данные за последние 30 дней, для аудита 90 хватает. |
| **REST API для управления** | Сейчас аналитик управляет правилами только через SQL-функции в DBeaver. REST позволил бы интеграции из других сервисов, CI или будущего GUI. Реализация - доп. слой на любом веб-фреймворке (FastAPI/aiohttp), под капотом вызывающий те же SQL-функции; никакой логики не дублируется.



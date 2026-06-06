# Дипломный проект - 
# Автоматизированный сервис сервис уведомлений на основе событий

Схемы:
- `diploma_architecture.drawio` дипломная часть
- `diploma_architecture_full.drawio` весь проект

---

## Идея

В существующем онлайн-кинотеатре уже работают два конвейера: `activity-tracker -> Kafka -> StarRocks` (события пользователей) и `notifications-service` (доставка писем и WebSocket). Между ними не хватает звена, замыкающего контур «данные -> действие». Это и делает новый сервис `alerting-service`: продуктовый аналитик пишет SQL-правило (`SELECT user_id, context FROM mv_*`) и регистрирует его одной функцией `alerting.adm_create_rule(...)`. Движок по расписанию выполняет запрос в StarRocks, отсекает пользователей, попавших под лимит уведомлений, и одной транзакцией создаёт задачу для `notifications-service`.

## Бизнес-ценность

Это автоматизация типовых рассылок по поведению пользователей: возврат ушедшего пользователя (win-back), тренд в сегменте -> рассылка промо, массовые отказы от просмотра новинки -> рекомендация альтернативы. Готовые аналоги - Mindbox, Customer.io, Braze. Отличие диплома: оптимизировано не под маркетолога без SQL (визуальные конструкторы условий), а под аналитика с SQL. Отсюда радикально проще интерфейс (одна SQL-функция вместо движка с UI) и максимум гибкости (любая логика выражается одним `SELECT`).

## Что добавляется/меняется в проекте

**Новые сервисы:**

| Сервис | Роль |
|---|---|
| `alerting-engine` | Главный артефакт. Планировщик APScheduler + исполнитель SQL поверх StarRocks + двухуровневый лимит уведомлений + восстановление после сбоя. |
| `alerting-migrations` | Init-контейнер: миграции схемы `alerting` в Postgres, SQL-функции `adm_*`, регистрация шаблонов уведомлений через `notifications.adm_upsert_template`. |
| `starrocks-dims-init` | Init-контейнер: DDL для `dim_*` (включая `dim_date` поверх ранее неиспользуемого `content.date_dimension`) и `mv_*`, JDBC Catalog поверх Postgres, `SUBMIT TASK ... SCHEDULE EVERY 1 HOUR` для синхронизации измерений, роль `alert_reader`. |
| `superset` (Apache Superset 6.1.0) | Дашборды поверх Materialized views (`starrocks_analytics` datasource через официальный SQLAlchemy dialect `starrocks://`). |
| `superset-db-init` | Init-контейнер: создаёт базу `superset` в общей `movies-db` (по образцу `sentry-db-init`). |
| `demo-tools` (profile `demo`) | Один Docker-образ с двумя Typer-подкомандами: `seed-users` и `trigger-events`. Запуск только вручную: `docker compose --profile demo run --rm movies-demo-tools <cmd>`. |

**Изменения в существующих сервисах:**

| Сервис | Изменение | Цель |
|---|---|---|
| `auth-service` | Миграция: добавить в `auth.users` nullable-колонки `gender / age / country / is_demo` + расширить схему профиля. | Чтобы у справочника `dim_users` были поля сегментации. |
| `activity-tracker-service` | Новый event_type `recommendation` (`POST /ugc/api/v1/events/recommendation`, Kafka-топик `recommendations`, поля `rule_code`/`notification_message_id`/`action`). | Замыкает контур «правило → письмо → клик → факт в StarRocks». Аналитик в Superset считает конверсию своих собственных правил. |
| `starrocks_init/init.sql` | `user_events` — переведена в **Primary Key table** по `(request_id, event_type)` для встроенной дедупликации через REPLACE-семантику. Добавлена Routine Load `recommendations_load`. | Защита от дублей при ретраях Kafka/Routine Load без работы на стороне правил. |

## Архитектура (поток данных)

Подробная схема - `diploma_architecture.drawio`. Кратко поток состоит из четырёх стадий:

1. **Источники данных в StarRocks.** События попадают из Kafka в таблицу `user_events` через Routine Load. Таблицы справочников (`dim_films`, `dim_users`, `dim_genres`) синхронизируются из Postgres средствами самого StarRocks - JDBC Catalog + `SUBMIT TASK ... SCHEDULE EVERY 1 HOUR`. Materialized views (`mv_*`) асинхронно пересчитываются поверх `user_events` и `dim_*`.
2. **Регистрация правила.** Аналитик в DBeaver вызывает `alerting.adm_create_rule(SQL, расписание, ...)` - правило сохраняется в `alerting.t_rules`.
3. **Срабатывание правила (`alerting-engine`).** Движок по расписанию правила выполняет `SELECT user_id, context FROM mv_*` в StarRocks, отсекает пользователей под лимитом уведомлений и одной транзакцией создаёт задачу через `notifications.adm_create_task(...)` с идемпотентным ключом.
4. **Доставка (`notifications-service`, уже существует).** Очередь исходящих -> RabbitMQ -> email-sender -> Mailpit.

Итого: событие в Kafka -> агрегат в Materialized view -> выборка SQL-правила -> задача в `notifications-service` -> письмо.

## Технологический стек + обоснование

| Компонент | Выбор | Почему |
|---|---|---|
| Движок | Python 3.12 + APScheduler | Стек проекта; APScheduler в том же процессе достаточен (распределённой очереди не нужно - она уже в `notifications-service`). |
| Доступ к StarRocks | MySQL-протокол через `aiomysql` / SQLAlchemy | StarRocks нативно говорит по MySQL. |
| Синхронизация dim-таблиц | StarRocks JDBC Catalog + `SUBMIT TASK` | Нативный механизм StarRocks, аналог Routine Load для пакетной загрузки. Отдельный Python ETL-сервис избыточен для трёх таблиц с полной перезаливкой раз в час. |
| BI | Apache Superset | Open-source, есть MySQL-коннектор для StarRocks, лучше Metabase на аналитических объёмах. |

## План работ

- **Неделя 1.[2026-05-18 -> 2026-05-24]** Выбор тема, составление ТЗ, диаграмма архитектуры, обоснование, связаться с наставником.
- **Неделя 2.[2026-05-25 -> 2026-05-31]** Миграция alembic `auth-service`, утилиты `demo-seeder` / `event-trigger`, init-контейнер StarRocks (DDL + JDBC Catalog + `SUBMIT TASK`), миграции схемы `alerting`, SQL-функции управления правилами, минимальный end-to-end движок (SQL → StarRocks → `notifications.adm_create_task` → письмо в Mailpit; dry-run и ручной запуск через `pg_notify`; проверен чистым прогоном с нуля), Superset. Аналитическая записка.
- **Неделя 3.[2026-06-01 -> 2026-06-07]** Полный движок: цикл планировщика, передача per-user `context` из SQL-правила в шаблон письма (ФТ-2), двухуровневый лимит уведомлений (ФТ-3), `t_dispatch_history` с партиционированием (ФТ-8), восстановление прерванных запусков после сбоя (НФТ-3), юнит-тесты бизнес-логики движка и сквозной тест с Mailpit (НФТ-6). Настроено логирование (подключение к ELK) и мониторинг ошибок Glitchtip (Sentry). Все скрипты для демонстрации должны быть готовы. Финальная отладка. Документация. Демо ревьюеру/наставнику.
- **Неделя 4.[2026-06-08 -> 2026-06-14]** Доработки по замечаниям ревьюера, защита работы.

## 3 главных архитектурных решения

1. **Интерфейс управления - SQL-функции в Postgres, а не REST.** Целевой пользователь - аналитик в DBeaver, ему естественнее `SELECT alerting.adm_create_rule(...)`, чем `curl`. Меньше слоёв, меньше кода. REST оставлен в «возможных улучшениях» - реализуется тонкой обёрткой поверх тех же функций без дублирования логики.
2. **Синхронизация dim-таблиц через JDBC Catalog + `SUBMIT TASK`, а не отдельным Python-сервисом.** Логика та же, что у Routine Load для Kafka-потока - «оркестрация внутри StarRocks». Минус один сервис, плюс правильный DWH-нарратив. Отдельный Python-воркер (как `films-etl-service` для Elasticsearch) был бы оправдан при CDC или сложных преобразованиях - здесь это избыточно.
3. **Идемпотентность срабатывания через `notifications.adm_create_task(p_idempotency_key := 'alerting:{rule_id}:{run_id}')`.** Цепочка «вычислили выборку -> применили лимит -> записали в `t_dispatch_history` -> создали задачу» оборачивается в одну транзакцию. Ключ задачи детерминирован от `run_id`, поэтому повтор после сбоя дублей не даст.



# notifications-service

Сервис уведомлений на основе паттерна **Outbox + RabbitMQ + DLX**.

## Архитектура

- **БД (схема `notifications` в `movies-db`)** - источник истины и журнал сообщений.
- **RabbitMQ** - транспорт доставки от outbox publisher к sender'ам.
- **Mailpit** - локальный SMTP-приёмник для разработки.

Воркеры (один Docker-образ, разные `command` в compose):
- `scheduler` - раскрывает аудиторию, ходит в auth за данными пользователя, рендерит шаблон, создаёт записи в `t_messages` (status=pending).
- `publisher` - claim-batch'ами переводит pending -> queued, публикует id в RabbitMQ.
- `email-sender` - consumer `q.email`, проверяет идемпотентность, отправляет письма через SMTP.
- `ws-gateway` - FastAPI WebSocket endpoint + consumer `q.ws`; доставляет in-app уведомления онлайн-пользователям.
- `recovery` - раз в N минут возвращает «застрявшие» queued/sending в pending.

## SQL-API: соглашение об именовании

Все SQL-объекты находятся в схеме `notifications`.

| Префикс | Кто вызывает | Описание |
|---|---|---|
| `adm_*` | Роль `notification_admin`  | Управление шаблонами и заданиями |
| `_*` | Python-воркеры и другие сервисы | Внутренние/служебные функции (как `_*` в alerting; роли `notification_admin` не выдаются) |
| `v_*` | Роль `notification_admin` | Мониторинговые представления |
| `t_*` | - | Таблицы (прямой доступ только у суперпользователя) |

## Функции для администратора

| SQL-Функция | Назначение |
|---|---|
| `adm_upsert_template` | Создать или обновить шаблон уведомления (адресуется по `code`) |
| `adm_create_task` | Создать задание на рассылку (можно задать бизнес-ключ `p_code`) |
| `adm_update_task` | Изменить параметры задания по `code` (NULL = не менять) |
| `adm_enable_task` | Включить задание по `code` |
| `adm_disable_task` | Отключить задание по `code` |

Управление существующим заданием (`adm_update_task` / `adm_enable_task` /
`adm_disable_task`) идёт по человекочитаемому `code`, а не по `uuid` — так же, как
правилами в alerting. `code` задаётся в `adm_create_task(p_code := ...)`; одноразовым
и программным рассылкам его можно не задавать (тогда они управляются только программно).

Все `adm_*` функции помечены `SECURITY DEFINER` - роль `notification_admin` не требует прямого доступа к таблицам.


## Представления

| Представление | Описание |
|---|---|
| `v_tasks` | Задания с раскрытым кодом и именем шаблона |
| `v_messages` | Журнал сообщений: статус, попытки, ошибки (без поля body) |

## Роль notification_admin

Групповая роль для администраторов уведомлений. Позволяет работать с уведомлениями например через DBeaver без прямого доступа к таблицам.

**Что входит в роль:**
- `USAGE ON SCHEMA notifications`
- `EXECUTE` на все `adm_*` функции
- `SELECT` на представления `v_tasks` и `v_messages`

**Создание пользователя-администратора** (выполнить под `postgres`):

```sql
-- Создать личного пользователя с паролем
CREATE USER notifications_admin_ivanov WITH PASSWORD 'strong_password';

-- Выдать групповую роль
GRANT notification_admin TO notifications_admin_ivanov;
```


## Примеры вызовов из DBeaver

```sql
-- Одноразовое письмо одному пользователю
SELECT notifications.adm_create_task(
    p_template_code   := 'welcome',
    p_channel         := 'email',
    p_audience        := '{"type": "user_ids", "values": ["<user_uuid>"]}'::jsonb,
    p_idempotency_key := 'welcome-<user_uuid>'
);

-- Массовая email-рассылка всем прямо сейчас
SELECT notifications.adm_create_task(
    p_template_code := 'new_film',
    p_channel       := 'email',
    p_audience      := '{"type": "all_users"}'::jsonb,
    p_name          := 'Новый фильм: Дюна 3',
    p_params        := '{"film_title": "Дюна 3", "film_year": 2026, "film_genres": ["sci-fi"]}'::jsonb
);

-- Cron-задание: каждую пятницу в 18:00.
-- p_code задаёт бизнес-ключ, по которому потом управляем заданием.
SELECT notifications.adm_create_task(
    p_template_code   := 'system_announcement',
    p_channel         := 'ws',
    p_audience        := '{"type": "all_users"}'::jsonb,
    p_name            := 'Пятничный дайджест',
    p_params          := '{"title": "Дайджест", "message": "Подборка недели"}'::jsonb,
    p_cron_expression := '0 18 * * 5',
    p_code            := 'friday_digest'
);

-- Отключить / включить задание по его code
SELECT notifications.adm_disable_task('friday_digest');
SELECT notifications.adm_enable_task('friday_digest');

-- Мониторинг
SELECT * FROM notifications.v_tasks ORDER BY next_run_at;
SELECT * FROM notifications.v_messages ORDER BY created_at DESC LIMIT 50;

-- Только проблемные
SELECT * FROM notifications.v_messages
WHERE status IN ('dead', 'failed') OR last_error IS NOT NULL
ORDER BY created_at DESC;
```

Полный список примеров - в `scripts/admin_examples.sql`.

## Идемпотентность

| Слой | Гарантия |
|---|---|
| `adm_create_task` / `_send_user_event` | UNIQUE по `idempotency_key` |
| Scheduler -> t_messages | UNIQUE `(task_id, user_id, run_at)` |
| Sender | `SELECT FOR UPDATE` + проверка статуса в `_mark_message_sending` |
| SMTP | Header `Message-ID = <message_id>` |

## Запуск

```bash
# Поднять всю инфраструктуру + сервис нотификаций
docker compose up -d movies-db movies-rabbitmq movies-mailpit \
    movies-notifications-migrations \
    movies-notifications-rabbit-init \
    movies-notifications-scheduler \
    movies-notifications-publisher \
    movies-notifications-email-sender-1 \
    movies-notifications-email-sender-2 \
    movies-notifications-ws-gateway \
    movies-notifications-recovery

# Быстрая проверка: письмо пользователю alice (в psql или DBeaver)
SELECT notifications.adm_create_task(
    p_template_code   := 'welcome',
    p_channel         := 'email',
    p_audience        := jsonb_build_object('type','user_ids','values',
                             jsonb_build_array((SELECT id FROM auth.users WHERE login='alice')::text)),
    p_idempotency_key := 'welcome-alice-test'
);
-- Mailpit UI: http://localhost:8025
```

## Топология RabbitMQ

```
exchange  notifications        (direct, durable)
exchange  notifications.dlx    (direct, durable)
queue     q.email   <- binding notifications:email  (x-dead-letter -> notifications.dlx)
queue     q.ws      <- binding notifications:ws     (x-dead-letter -> notifications.dlx)
queue     q.dead    <- bindings notifications.dlx:email + notifications.dlx:ws
```

## Гарантии и компромиссы

Гарантия доставки - **at-least-once**, не exactly-once.

**Защита от дублей RabbitMQ.** Sender первым делом вызывает `_mark_message_sending` (`SELECT FOR UPDATE` + проверка статуса). Если статус уже `sent` - сообщение ack-ается без работы. Дубль AMQP-сообщения (например, из-за race condition в publisher) безопасен.

**Незащищённое окно (email).** Если процесс упал между SMTP success и `mark_message_sent` - recovery вернёт сообщение в pending, письмо уйдёт повторно. Смягчается заголовком `Message-ID: <message_id>`: SMTP-провайдер может дедуплицировать повторную доставку. В Mailpit дедупликации нет.

**Незащищённое окно (WS).** Аналогичный сценарий - дубль WS-уведомления возможен; механизма дедупликации на уровне WebSocket нет. Клиент может дедуплицировать по `message_id` в payload самостоятельно.

**ACK/NACK.** RabbitMQ не удаляет сообщение из очереди, пока consumer не отправит `ack`. Если consumer упал без `ack`, сообщение возвращается в очередь. `reject(requeue=False)` направляет сообщение в DLX -> `q.dead`.

- DLX -> `q.dead` - для ручного разбора мёртвых сообщений. Recovery worker автоматически возвращает застрявшие queued/sending в pending.
- WS offline-случай: сообщение возвращается в pending через `_mark_message_failed(error='user offline')`; при длительном оффлайне в итоге уходит в dead.

## Структура

```
notifications-service/
├── alembic/                   # единая начальная миграция схемы notifications
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py    # таблицы + функции + представления + роль + сидинг
├── scripts/
│   └── admin_examples.sql     # готовые SQL-запросы для DBeaver
├── sql/
│   ├── functions/             # adm_* и _* функции (CREATE OR REPLACE)
│   ├── views/                 # v_tasks, v_messages
│   ├── roles/                 # notification_admin + GRANT
│   └── seed/                  # базовые шаблоны welcome, new_film, system_announcement
├── src/
│   ├── core/
│   ├── db/
│   ├── shared/
│   └── workers/
│       ├── bootstrap.py       # init-контейнер: объявить топологию RabbitMQ
│       ├── scheduler.py       # раскрыть аудиторию, создать t_messages
│       ├── publisher.py       # outbox: pending -> queued -> RabbitMQ
│       ├── email_sender.py    # consumer q.email -> SMTP
│       ├── ws_gateway.py      # consumer q.ws + WebSocket endpoint
│       └── recovery.py        # вернуть застрявшие queued/sending в pending
├── tests/
│   ├── conftest.py
│   └── test_end_to_end.py
├── pyproject.toml
└── Dockerfile
```

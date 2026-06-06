-- Примеры вызовов SQL-API notifications для администратора.
-- Открыть в DBeaver, подключившись к базе movies под пользователем с ролью notification_admin.
--
-- Соглашение об именовании функций:
--   adm_* — функции для администратора (доступны через роль notification_admin)
--   _*    — внутренние/сервисные функции (не выдаются notification_admin)

-- =============================================================================
-- Создание личного пользователя-администратора (выполнять под postgres)
-- =============================================================================

-- CREATE USER notifications_admin_ivanov WITH PASSWORD 'strong_password_here';
-- GRANT notification_admin TO notifications_admin_ivanov;

-- =============================================================================
-- Шаблоны (adm_upsert_template)
-- =============================================================================

-- Создать или обновить шаблон
SELECT notifications.adm_upsert_template(
    p_code             := 'welcome',
    p_name             := 'Приветственное письмо',
    p_subject_template := 'Добро пожаловать, {{ user.first_name | default(user.login) }}!',
    p_body_template    := 'Привет, {{ user.first_name | default(user.login) }}! Добро пожаловать на Movies.',
    p_body_format      := 'text',
    p_channel          := 'email'
);

-- =============================================================================
-- Одноразовая персональная отправка (adm_create_task)
-- =============================================================================

-- Письмо конкретному пользователю (замените UUID)
SELECT notifications.adm_create_task(
    p_template_code   := 'welcome',
    p_channel         := 'email',
    p_audience        := '{"type": "user_ids", "values": ["<user_uuid>"]}'::jsonb,
    p_idempotency_key := 'welcome-<user_uuid>'
);

-- =============================================================================
-- Массовые задания (adm_create_task)
-- =============================================================================

-- Email-рассылка всем пользователям прямо сейчас
SELECT notifications.adm_create_task(
    p_template_code := 'new_film',
    p_channel       := 'email',
    p_audience      := '{"type": "all_users"}'::jsonb,
    p_name          := 'Новый фильм: Дюна 3',
    p_params        := '{"film_title": "Дюна 3", "film_year": 2026, "film_genres": ["sci-fi"]}'::jsonb
);

-- Отложенная WS-рассылка (через 2 часа)
SELECT notifications.adm_create_task(
    p_template_code   := 'system_announcement',
    p_channel         := 'ws',
    p_audience        := '{"type": "all_users"}'::jsonb,
    p_name            := 'Тех.работы 2026-05-15',
    p_params          := '{"title": "Тех.работы", "message": "15 мая в 03:00 будет перезапуск."}'::jsonb,
    p_start_at        := now() + interval '2 hours',
    p_idempotency_key := 'maintenance-2026-05-15'
);

-- Повторяющееся задание: каждую пятницу в 18:00.
-- p_code — человекочитаемый бизнес-ключ; по нему потом управляем заданием
-- (включить/выключить/изменить), не разыскивая uuid.
SELECT notifications.adm_create_task(
    p_template_code   := 'system_announcement',
    p_channel         := 'ws',
    p_audience        := '{"type": "all_users"}'::jsonb,
    p_name            := 'Пятничный дайджест',
    p_params          := '{"title": "Дайджест", "message": "Подборка недели"}'::jsonb,
    p_cron_expression := '0 18 * * 5',
    p_code            := 'friday_digest'
);

-- Рассылка конкретным пользователям
SELECT notifications.adm_create_task(
    p_template_code := 'welcome',
    p_channel       := 'email',
    p_audience      := '{"type": "user_ids", "values": ["<uuid1>", "<uuid2>"]}'::jsonb,
    p_name          := 'Персональная акция'
);

-- =============================================================================
-- Управление заданиями
-- =============================================================================

-- Управление идёт по бизнес-ключу code (задаётся в adm_create_task(p_code := ...)),

-- Отключить задание
SELECT notifications.adm_disable_task('friday_digest');

-- Включить задание
SELECT notifications.adm_enable_task('friday_digest');

-- Изменить расписание задания (NULL-аргументы не меняют соответствующее поле)
SELECT notifications.adm_update_task(
    p_task_code       := 'friday_digest',
    p_cron_expression := '0 10 * * 1'  -- теперь каждый понедельник в 10:00
);

-- =============================================================================
-- Мониторинг (представления)
-- =============================================================================

-- Список заданий с раскрытым шаблоном
SELECT * FROM notifications.v_tasks ORDER BY next_run_at;

-- Журнал сообщений (статус, попытки, последняя ошибка)
SELECT * FROM notifications.v_messages ORDER BY created_at DESC LIMIT 50;

-- Только проблемные (dead или с ошибками)
SELECT * FROM notifications.v_messages
WHERE status IN ('dead', 'failed') OR last_error IS NOT NULL
ORDER BY created_at DESC LIMIT 50;

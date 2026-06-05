-- notifications.adm_create_task — создать задание на рассылку.
-- Вызывается администратором или другими сервисами через API.
--
-- p_audience — JSONB-описание получателей. Поддерживаемые форматы:
--   {"type": "all_users"}                                  -- все активные пользователи
--   {"type": "user_ids", "values": ["<uuid>", "<uuid>"]}   -- явный список UUID
CREATE OR REPLACE FUNCTION notifications.adm_create_task(
    p_template_code   TEXT,
    p_channel         TEXT,
    p_audience        JSONB,
    p_name            TEXT      DEFAULT NULL,
    p_params          JSONB     DEFAULT '{}'::jsonb,
    p_cron_expression TEXT      DEFAULT NULL,
    p_start_at        TIMESTAMP DEFAULT NULL,
    p_end_at          TIMESTAMP DEFAULT NULL,
    p_idempotency_key TEXT      DEFAULT NULL,
    p_created_by      TEXT      DEFAULT 'admin',
    p_code            TEXT      DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
DECLARE
    v_template_id UUID;
    v_task_id     UUID;
    v_start_at    TIMESTAMP;
BEGIN
    IF p_channel NOT IN ('email', 'ws') THEN
        RAISE EXCEPTION 'invalid_channel: %', p_channel;
    END IF;

    SELECT id INTO v_template_id
    FROM notifications.t_templates
    WHERE code = p_template_code AND is_active = TRUE;

    IF v_template_id IS NULL THEN
        RAISE EXCEPTION 'template_not_found_or_inactive: %', p_template_code;
    END IF;

    v_start_at := COALESCE(p_start_at, (now() AT TIME ZONE 'utc'));

    IF p_idempotency_key IS NOT NULL THEN
        SELECT id INTO v_task_id FROM notifications.t_tasks
        WHERE idempotency_key = p_idempotency_key;
        IF v_task_id IS NOT NULL THEN
            RETURN v_task_id;
        END IF;
    END IF;

    INSERT INTO notifications.t_tasks(
        code, name, template_id, channel, audience, params,
        cron_expression, start_at, end_at,
        is_enabled, next_run_at, created_by, idempotency_key
    ) VALUES (
        p_code,
        COALESCE(p_name, 'task:' || p_template_code),
        v_template_id,
        p_channel,
        p_audience,
        COALESCE(p_params, '{}'::jsonb),
        p_cron_expression,
        v_start_at,
        p_end_at,
        TRUE,
        v_start_at,
        p_created_by,
        p_idempotency_key
    )
    RETURNING id INTO v_task_id;

    RETURN v_task_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.adm_create_task(TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TIMESTAMP, TIMESTAMP, TEXT, TEXT, TEXT) IS
'Создать задание на рассылку уведомлений. Идемпотентна через p_idempotency_key.

Аргументы:
  p_template_code   TEXT            — код активного шаблона (см. t_templates.code)
  p_channel         TEXT            — канал доставки: ''email'' | ''ws''
  p_audience        JSONB           — получатели: {"type":"all_users"} или {"type":"user_ids","values":["<uuid>",...]}
  p_name            TEXT  DEFAULT NULL — имя задания; если NULL — ''task:<template_code>''
  p_params          JSONB DEFAULT {} — дополнительные параметры для Jinja2-шаблона
  p_cron_expression TEXT  DEFAULT NULL — cron-расписание (напр. ''0 9 * * 1''); NULL = одноразово
  p_start_at        TIMESTAMP DEFAULT NULL — старт; NULL = немедленно
  p_end_at          TIMESTAMP DEFAULT NULL — окончание; NULL = бессрочно
  p_idempotency_key TEXT  DEFAULT NULL — уникальный ключ; при повторном вызове вернёт существующий task_id
  p_created_by      TEXT  DEFAULT ''admin'' — метка автора для аудита
  p_code            TEXT  DEFAULT NULL — человекочитаемый бизнес-ключ задания (uq_t_tasks_code).
                                        Задайте, чтобы потом управлять заданием через
                                        adm_enable_task / adm_disable_task / adm_update_task по code.
                                        Одноразовым/программным рассылкам можно не задавать.

Возвращает UUID созданного (или найденного по idempotency_key) задания.';

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_create_task(TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TIMESTAMP, TIMESTAMP, TEXT, TEXT, TEXT)
    TO notification_admin;

-- notifications.adm_update_task — изменить параметры задания.
-- NULL-аргументы оставляют соответствующее поле без изменений.
CREATE OR REPLACE FUNCTION notifications.adm_update_task(
    p_task_id         UUID,
    p_cron_expression TEXT      DEFAULT NULL,
    p_start_at        TIMESTAMP DEFAULT NULL,
    p_end_at          TIMESTAMP DEFAULT NULL,
    p_audience        JSONB     DEFAULT NULL,
    p_params          JSONB     DEFAULT NULL,
    p_template_code   TEXT      DEFAULT NULL,
    p_channel         TEXT      DEFAULT NULL,
    p_name            TEXT      DEFAULT NULL
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
DECLARE
    v_template_id UUID;
BEGIN
    IF p_channel IS NOT NULL AND p_channel NOT IN ('email', 'ws') THEN
        RAISE EXCEPTION 'invalid_channel: %', p_channel;
    END IF;

    IF p_template_code IS NOT NULL THEN
        SELECT id INTO v_template_id
        FROM notifications.t_templates
        WHERE code = p_template_code AND is_active = TRUE;
        IF v_template_id IS NULL THEN
            RAISE EXCEPTION 'template_not_found_or_inactive: %', p_template_code;
        END IF;
    END IF;

    UPDATE notifications.t_tasks SET
        cron_expression = COALESCE(p_cron_expression, cron_expression),
        start_at        = COALESCE(p_start_at, start_at),
        end_at          = CASE WHEN p_end_at IS NULL THEN end_at ELSE p_end_at END,
        audience        = COALESCE(p_audience, audience),
        params          = COALESCE(p_params, params),
        template_id     = COALESCE(v_template_id, template_id),
        channel         = COALESCE(p_channel, channel),
        name            = COALESCE(p_name, name),
        next_run_at     = COALESCE(p_start_at, next_run_at),
        updated_at      = (now() AT TIME ZONE 'utc')
    WHERE id = p_task_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'task_not_found: %', p_task_id;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.adm_update_task(UUID, TEXT, TIMESTAMP, TIMESTAMP, JSONB, JSONB, TEXT, TEXT, TEXT) IS
'Изменить параметры существующего задания на рассылку.
NULL-аргументы оставляют соответствующие поля без изменений.

Аргументы:
  p_task_id         UUID            — идентификатор задания
  p_cron_expression TEXT DEFAULT NULL — новое cron-расписание; NULL = не менять
  p_start_at        TIMESTAMP DEFAULT NULL — новое время старта; NULL = не менять
  p_end_at          TIMESTAMP DEFAULT NULL — новое время окончания; NULL = не менять
  p_audience        JSONB DEFAULT NULL — новый список получателей; NULL = не менять
  p_params          JSONB DEFAULT NULL — новые параметры шаблона; NULL = не менять
  p_template_code   TEXT DEFAULT NULL — код нового шаблона; NULL = не менять
  p_channel         TEXT DEFAULT NULL — новый канал: ''email'' | ''ws''; NULL = не менять
  p_name            TEXT DEFAULT NULL — новое имя задания; NULL = не менять

Выбрасывает исключение task_not_found если задание не существует.';

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_update_task(UUID, TEXT, TIMESTAMP, TIMESTAMP, JSONB, JSONB, TEXT, TEXT, TEXT)
    TO notification_admin;

-- notifications.svc_send_user_event — API для других сервисов:
-- одно сообщение конкретному пользователю по коду шаблона.
-- Фасад над adm_create_task: формирует audience автоматически.
CREATE OR REPLACE FUNCTION notifications.svc_send_user_event(
    p_user_id         UUID,
    p_template_code   TEXT,
    p_channel         TEXT   DEFAULT 'email',
    p_params          JSONB  DEFAULT '{}'::jsonb,
    p_idempotency_key TEXT   DEFAULT NULL,
    p_created_by      TEXT   DEFAULT 'system'
) RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_audience JSONB;
BEGIN
    v_audience := jsonb_build_object(
        'type', 'user_ids',
        'values', jsonb_build_array(p_user_id::TEXT)
    );

    RETURN notifications.adm_create_task(
        p_template_code   := p_template_code,
        p_channel         := p_channel,
        p_audience        := v_audience,
        p_name            := 'event:' || p_template_code || ':' || p_user_id::TEXT,
        p_params          := p_params,
        p_cron_expression := NULL,
        p_start_at        := (now() AT TIME ZONE 'utc'),
        p_end_at          := NULL,
        p_idempotency_key := p_idempotency_key,
        p_created_by      := p_created_by
    );
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.svc_send_user_event(UUID, TEXT, TEXT, JSONB, TEXT, TEXT) IS
'Отправить одно уведомление конкретному пользователю. Фасад над adm_create_task.
Предназначена для вызова из других бэкенд-сервисов (auth, billing и др.).

Аргументы:
  p_user_id         UUID           — идентификатор получателя
  p_template_code   TEXT           — код активного шаблона
  p_channel         TEXT DEFAULT ''email'' — канал: ''email'' | ''ws''
  p_params          JSONB DEFAULT {} — дополнительные параметры шаблона
  p_idempotency_key TEXT DEFAULT NULL — ключ идемпотентности; повторный вызов вернёт тот же task_id
  p_created_by      TEXT DEFAULT ''system'' — метка автора для аудита

Возвращает UUID задания (нового или найденного по idempotency_key).';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications.svc_send_user_event(UUID, TEXT, TEXT, JSONB, TEXT, TEXT)
    FROM PUBLIC;

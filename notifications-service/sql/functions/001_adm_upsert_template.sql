-- notifications.adm_upsert_template — создать или обновить шаблон уведомления.
-- Вызывается администратором из DBeaver.
CREATE OR REPLACE FUNCTION notifications.adm_upsert_template(
    p_code             TEXT,
    p_name             TEXT,
    p_subject_template TEXT,
    p_body_template    TEXT,
    p_body_format      TEXT    DEFAULT 'text',
    p_channel          TEXT    DEFAULT 'any',
    p_is_active        BOOLEAN DEFAULT TRUE
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
DECLARE
    v_id UUID;
BEGIN
    IF p_body_format NOT IN ('text', 'html') THEN
        RAISE EXCEPTION 'invalid_body_format: %', p_body_format;
    END IF;
    IF p_channel NOT IN ('email', 'ws', 'any') THEN
        RAISE EXCEPTION 'invalid_channel: %', p_channel;
    END IF;

    INSERT INTO notifications.t_templates(
        code, name, subject_template, body_template,
        body_format, channel, is_active
    ) VALUES (
        p_code, p_name, p_subject_template, p_body_template,
        p_body_format, p_channel, p_is_active
    )
    ON CONFLICT (code) DO UPDATE SET
        name             = EXCLUDED.name,
        subject_template = EXCLUDED.subject_template,
        body_template    = EXCLUDED.body_template,
        body_format      = EXCLUDED.body_format,
        channel          = EXCLUDED.channel,
        is_active        = EXCLUDED.is_active,
        updated_at       = (now() AT TIME ZONE 'utc')
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.adm_upsert_template(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN) IS
'Создать или обновить шаблон уведомления. Идемпотентна: повторный вызов обновит поля.

Аргументы:
  p_code             TEXT            — уникальный код шаблона (slug), напр. ''welcome''
  p_name             TEXT            — человекочитаемое название
  p_subject_template TEXT            — Jinja2-шаблон темы письма
  p_body_template    TEXT            — Jinja2-шаблон тела сообщения
  p_body_format      TEXT  DEFAULT ''text'' — формат тела: ''text'' | ''html''
  p_channel          TEXT  DEFAULT ''any''  — целевой канал: ''email'' | ''ws'' | ''any''
  p_is_active        BOOL  DEFAULT TRUE     — активен ли шаблон (неактивные не используются планировщиком)

Возвращает UUID созданного или обновлённого шаблона.';

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_upsert_template(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN)
    TO notification_admin;

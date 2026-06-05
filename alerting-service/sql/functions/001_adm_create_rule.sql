-- alerting.adm_create_rule — создать правило. Идемпотентна через p_idempotency_key.
--
-- Валидация:
--   p_channel               — 'email' | 'ws'
--   p_template_code         — должен существовать в notifications.t_templates (is_active=TRUE)
--   p_cron                  — синтаксически валидное cron-выражение (5 полей)
--   p_frequency_cap         — JSONB-объект, может быть пустым
--   p_max_users             — > 0
CREATE OR REPLACE FUNCTION alerting.adm_create_rule(
    p_code            TEXT,
    p_description     TEXT,
    p_sql             TEXT,
    p_cron            TEXT,
    p_template_code   TEXT,
    p_channel         TEXT,
    p_frequency_cap   JSONB    DEFAULT '{}'::jsonb,
    p_max_users       INTEGER  DEFAULT 50000,
    p_idempotency_key TEXT     DEFAULT NULL,
    p_created_by      TEXT     DEFAULT 'admin'
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting, notifications
AS $$
DECLARE
    v_rule_id UUID;
BEGIN
    PERFORM alerting._check_channel(p_channel);
    PERFORM alerting._check_cron(p_cron);

    IF p_max_users IS NULL OR p_max_users <= 0 THEN
        RAISE EXCEPTION 'invalid_max_users: must be > 0';
    END IF;

    -- Проверяем существование активного шаблона в notifications.
    IF NOT EXISTS (
        SELECT 1 FROM notifications.t_templates
        WHERE code = p_template_code AND is_active = TRUE
    ) THEN
        RAISE EXCEPTION 'template_not_found_or_inactive: %', p_template_code;
    END IF;

    -- Идемпотентность по p_idempotency_key.
    IF p_idempotency_key IS NOT NULL THEN
        SELECT id INTO v_rule_id FROM alerting.t_rules
        WHERE idempotency_key = p_idempotency_key;
        IF v_rule_id IS NOT NULL THEN
            RETURN v_rule_id;
        END IF;
    END IF;

    INSERT INTO alerting.t_rules(
        code, description, sql_query, cron_expression, template_code,
        channel, frequency_cap, max_users, idempotency_key, created_by
    ) VALUES (
        p_code, p_description, p_sql, p_cron, p_template_code,
        p_channel, COALESCE(p_frequency_cap, '{}'::jsonb),
        p_max_users, p_idempotency_key, p_created_by
    )
    RETURNING id INTO v_rule_id;

    RETURN v_rule_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_create_rule(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT, TEXT) IS
'Создать правило alerting. Идемпотентна через p_idempotency_key.

Аргументы:
  p_code            TEXT  — уникальный slug правила (напр. ''winback_active_user'')
  p_description     TEXT  — описание для аналитика
  p_sql             TEXT  — SQL-запрос в StarRocks, обязан возвращать колонку user_id (+ опционально context jsonb)
  p_cron            TEXT  — cron-расписание срабатывания (5 полей)
  p_template_code   TEXT  — код активного шаблона из notifications.t_templates
  p_channel         TEXT  — ''email'' | ''ws''
  p_frequency_cap   JSONB DEFAULT {} — лимиты вида {"per_rule_per_user_days": 30, "per_user_per_day": 1}
  p_max_users       INT   DEFAULT 50000 — потолок выборки
  p_idempotency_key TEXT  DEFAULT NULL  — уникальный ключ, повтор вернёт существующий rule_id
  p_created_by      TEXT  DEFAULT ''admin''

Создано отключённым (is_enabled=FALSE). Включить — alerting.adm_enable_rule(code).';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_create_rule(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT, TEXT)
    TO alerting_admin;

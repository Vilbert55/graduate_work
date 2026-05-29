-- alerting.adm_update_rule — изменить параметры правила.
-- NULL-аргумент оставляет соответствующее поле без изменений.
CREATE OR REPLACE FUNCTION alerting.adm_update_rule(
    p_rule_id         UUID,
    p_sql             TEXT     DEFAULT NULL,
    p_cron            TEXT     DEFAULT NULL,
    p_template_code   TEXT     DEFAULT NULL,
    p_channel         TEXT     DEFAULT NULL,
    p_frequency_cap   JSONB    DEFAULT NULL,
    p_max_users       INTEGER  DEFAULT NULL,
    p_description     TEXT     DEFAULT NULL
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting, notifications
AS $$
BEGIN
    IF p_channel IS NOT NULL AND p_channel NOT IN ('email', 'ws') THEN
        RAISE EXCEPTION 'invalid_channel: %', p_channel;
    END IF;

    IF p_max_users IS NOT NULL AND p_max_users <= 0 THEN
        RAISE EXCEPTION 'invalid_max_users: must be > 0';
    END IF;

    IF p_cron IS NOT NULL AND p_cron !~ '^\S+\s+\S+\s+\S+\s+\S+\s+\S+$' THEN
        RAISE EXCEPTION 'invalid_cron: %', p_cron;
    END IF;

    IF p_template_code IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM notifications.t_templates
        WHERE code = p_template_code AND is_active = TRUE
    ) THEN
        RAISE EXCEPTION 'template_not_found_or_inactive: %', p_template_code;
    END IF;

    UPDATE alerting.t_rules SET
        sql_query        = COALESCE(p_sql, sql_query),
        cron_expression  = COALESCE(p_cron, cron_expression),
        template_code    = COALESCE(p_template_code, template_code),
        channel          = COALESCE(p_channel, channel),
        frequency_cap    = COALESCE(p_frequency_cap, frequency_cap),
        max_users        = COALESCE(p_max_users, max_users),
        description      = COALESCE(p_description, description),
        updated_at       = (now() AT TIME ZONE 'utc')
    WHERE id = p_rule_id AND is_deleted = FALSE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_id;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_update_rule(UUID, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT) IS
'Изменить параметры правила. NULL-аргументы оставляют поля без изменений.
Бросает rule_not_found если правило не существует или мягко удалено.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_update_rule(UUID, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT)
    TO alerting_admin;

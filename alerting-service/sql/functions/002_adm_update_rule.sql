-- alerting.adm_update_rule — изменить параметры правила.
-- NULL-аргумент оставляет соответствующее поле без изменений.
CREATE OR REPLACE FUNCTION alerting.adm_update_rule(
    p_rule_code       TEXT,
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
DECLARE
    v_rule_id UUID := alerting._rule_id(p_rule_code);
BEGIN
    PERFORM alerting._check_rule_sql(p_sql);
    PERFORM alerting._check_channel(p_channel);
    PERFORM alerting._check_cron(p_cron);
    PERFORM alerting._check_frequency_cap(p_frequency_cap);

    IF p_max_users IS NOT NULL AND p_max_users <= 0 THEN
        RAISE EXCEPTION 'invalid_max_users: must be > 0';
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
    WHERE id = v_rule_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_code;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_update_rule(TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT) IS
'Изменить параметры правила (адресуется по code). NULL-аргументы оставляют поля
без изменений. Бросает rule_not_found если правило не существует.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_update_rule(TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, INTEGER, TEXT)
    TO alerting_admin;

-- alerting.adm_enable_rule / adm_disable_rule — переключатели правила.

CREATE OR REPLACE FUNCTION alerting.adm_enable_rule(p_rule_code TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    UPDATE alerting.t_rules
       SET is_enabled = TRUE,
           updated_at = (now() AT TIME ZONE 'utc')
     WHERE id = alerting._rule_id(p_rule_code);
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_enable_rule(TEXT) IS
'Включить правило по code (is_enabled := TRUE). Движок подхватит изменение на
ближайшем обновлении расписания.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_enable_rule(TEXT) TO alerting_admin;

-- @statement

CREATE OR REPLACE FUNCTION alerting.adm_disable_rule(p_rule_code TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    UPDATE alerting.t_rules
       SET is_enabled = FALSE,
           updated_at = (now() AT TIME ZONE 'utc')
     WHERE id = alerting._rule_id(p_rule_code);
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_disable_rule(TEXT) IS
'Выключить правило по code (is_enabled := FALSE). Движок снимает его с расписания.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_disable_rule(TEXT) TO alerting_admin;

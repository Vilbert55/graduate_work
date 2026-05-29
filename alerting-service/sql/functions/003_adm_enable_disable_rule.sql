-- alerting.adm_enable_rule / adm_disable_rule — переключатели правила.

CREATE OR REPLACE FUNCTION alerting.adm_enable_rule(p_rule_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    UPDATE alerting.t_rules
       SET is_enabled = TRUE,
           updated_at = (now() AT TIME ZONE 'utc')
     WHERE id = p_rule_id AND is_deleted = FALSE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_id;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_enable_rule(UUID) IS
'Включить правило (is_enabled := TRUE). Движок подхватит изменение на ближайшем
обновлении расписания.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_enable_rule(UUID) TO alerting_admin;

-- @statement

CREATE OR REPLACE FUNCTION alerting.adm_disable_rule(p_rule_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    UPDATE alerting.t_rules
       SET is_enabled = FALSE,
           updated_at = (now() AT TIME ZONE 'utc')
     WHERE id = p_rule_id AND is_deleted = FALSE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_id;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_disable_rule(UUID) IS
'Выключить правило (is_enabled := FALSE). Движок снимает его с расписания.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_disable_rule(UUID) TO alerting_admin;

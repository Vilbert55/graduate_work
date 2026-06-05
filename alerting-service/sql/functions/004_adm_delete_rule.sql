-- alerting.adm_delete_rule — мягкое удаление (is_deleted := TRUE).
CREATE OR REPLACE FUNCTION alerting.adm_delete_rule(p_rule_code TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    UPDATE alerting.t_rules
       SET is_deleted = TRUE,
           is_enabled = FALSE,
           updated_at = (now() AT TIME ZONE 'utc')
     WHERE id = alerting._rule_id(p_rule_code);
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_delete_rule(TEXT) IS
'Мягкое удаление правила по code: is_deleted := TRUE и is_enabled := FALSE.
Запись остаётся для аудита (через v_runs / v_dispatch).';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_delete_rule(TEXT) TO alerting_admin;

-- alerting.adm_delete_rule — мягкое удаление (is_deleted := TRUE).
CREATE OR REPLACE FUNCTION alerting.adm_delete_rule(p_rule_id UUID)
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
     WHERE id = p_rule_id AND is_deleted = FALSE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_id;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_delete_rule(UUID) IS
'Мягкое удаление правила: is_deleted := TRUE и is_enabled := FALSE.
Запись остаётся для аудита (через v_runs / v_dispatch).';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_delete_rule(UUID) TO alerting_admin;

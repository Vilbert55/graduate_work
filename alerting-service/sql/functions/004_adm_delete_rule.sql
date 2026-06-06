-- alerting.adm_delete_rule — полное удаление правила вместе с его историей.
CREATE OR REPLACE FUNCTION alerting.adm_delete_rule(p_rule_code TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
DECLARE
    v_rule_id UUID := alerting._rule_id(p_rule_code);   -- бросит rule_not_found
BEGIN
    -- Зависимые строки удаляем явно (всё в одной транзакции функции): t_runs
    -- связан с t_rules внешним ключом без ON DELETE, t_dispatch_history — без
    -- FK. Сначала зависимые, потом само правило.
    DELETE FROM alerting.t_dispatch_history WHERE rule_id = v_rule_id;
    DELETE FROM alerting.t_runs             WHERE rule_id = v_rule_id;
    DELETE FROM alerting.t_rules            WHERE id = v_rule_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_delete_rule(TEXT) IS
'Полное удаление правила по code вместе с историей запусков (t_runs) и отправок
(t_dispatch_history). После удаления code освобождается и доступен для повторного
использования.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_delete_rule(TEXT) TO alerting_admin;

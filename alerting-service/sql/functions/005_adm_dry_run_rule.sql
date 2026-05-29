-- alerting.adm_dry_run_rule — тестовый прогон правила без рассылки.
--
-- Создаёт t_runs со статусом 'running' и шлёт NOTIFY с payload
-- 'dryrun:{rule_id}:{run_id}'. Движок выполнит SQL, посчитает размер
-- аудитории и обновит t_runs (matched_users, after_cap_users), но
-- НЕ будет звать notifications.adm_create_task.
--
-- Возвращает run_id; аналитик дальше поллит alerting.v_runs:
--   SELECT matched_users, after_cap_users, status FROM alerting.v_runs WHERE run_id = ...
CREATE OR REPLACE FUNCTION alerting.adm_dry_run_rule(p_rule_id UUID)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
DECLARE
    v_run_id UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM alerting.t_rules
                    WHERE id = p_rule_id AND is_deleted = FALSE) THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_id;
    END IF;

    INSERT INTO alerting.t_runs(rule_id, status)
    VALUES (p_rule_id, 'running')
    RETURNING id INTO v_run_id;

    PERFORM pg_notify('alerting_trigger',
        'dryrun:' || p_rule_id::text || ':' || v_run_id::text);

    RETURN v_run_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_dry_run_rule(UUID) IS
'Тестовый прогон правила: выполняется SQL в StarRocks, считается
размер выборки, но notifications.adm_create_task НЕ вызывается.

Возвращает run_id. Прогресс/результат — через alerting.v_runs:
  SELECT matched_users, status, error FROM alerting.v_runs WHERE run_id = ...;';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_dry_run_rule(UUID) TO alerting_admin;

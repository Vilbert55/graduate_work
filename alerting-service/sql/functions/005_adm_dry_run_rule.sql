-- alerting.adm_dry_run_rule — тестовый прогон правила без рассылки.
--
-- Создаёт t_runs со статусом 'running' и шлёт NOTIFY с payload
-- 'dryrun:{rule_id}:{run_id}'. Движок выполнит SQL, посчитает размер
-- аудитории и обновит t_runs (matched_users, after_cap_users), но
-- НЕ будет звать notifications.adm_create_task.
--
-- Возвращает run_id; аналитик дальше поллит alerting.v_runs:
--   SELECT matched_users, after_cap_users, status FROM alerting.v_runs WHERE run_id = ...
CREATE OR REPLACE FUNCTION alerting.adm_dry_run_rule(p_rule_code TEXT)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    RETURN alerting._enqueue_rule_run(alerting._rule_id(p_rule_code), 'dryrun');
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_dry_run_rule(TEXT) IS
'Тестовый прогон правила (адресуется по code): выполняется SQL в StarRocks,
считается размер выборки, но notifications.adm_create_task НЕ вызывается.

Возвращает run_id. Прогресс/результат — через alerting.v_runs:
  SELECT matched_users, status, error FROM alerting.v_runs WHERE run_id = ...;';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_dry_run_rule(TEXT) TO alerting_admin;

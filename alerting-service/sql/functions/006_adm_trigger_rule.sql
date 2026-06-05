-- alerting.adm_trigger_rule — ручной запуск правила вне расписания.
--
-- Создаёт запись t_runs со статусом 'running' и шлёт NOTIFY с payload
-- 'trigger:{rule_id}:{run_id}'. alerting-engine слушает канал
-- alerting_trigger и подхватывает запрос.
CREATE OR REPLACE FUNCTION alerting.adm_trigger_rule(p_rule_code TEXT)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    RETURN alerting._enqueue_rule_run(alerting._rule_id(p_rule_code), 'trigger');
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_trigger_rule(TEXT) IS
'Ручной запуск правила вне расписания (адресуется по code). Возвращает run_id
(можно поллить
alerting.v_runs WHERE run_id = ... чтобы увидеть прогресс/результат).

Под капотом: создаётся t_runs со статусом ''running'' и шлётся
pg_notify(''alerting_trigger'', ''trigger:<rule_id>:<run_id>''). Движок
alerting-engine, подписанный на этот канал, выполнит SQL правила в
StarRocks и обновит t_runs.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_trigger_rule(TEXT) TO alerting_admin;

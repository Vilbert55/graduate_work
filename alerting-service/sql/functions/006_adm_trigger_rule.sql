-- alerting.adm_trigger_rule — ручной запуск правила вне расписания.
--
-- Создаёт запись t_runs со статусом 'running' и шлёт NOTIFY с payload
-- 'trigger:{rule_id}:{run_id}'. alerting-engine слушает канал
-- alerting_trigger и подхватывает запрос.
CREATE OR REPLACE FUNCTION alerting.adm_trigger_rule(p_rule_id UUID)
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
        'trigger:' || p_rule_id::text || ':' || v_run_id::text);

    RETURN v_run_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_trigger_rule(UUID) IS
'Ручной запуск правила вне расписания. Возвращает run_id (можно поллить
alerting.v_runs WHERE run_id = ... чтобы увидеть прогресс/результат).

Под капотом: создаётся t_runs со статусом ''running'' и шлётся
pg_notify(''alerting_trigger'', ''trigger:<rule_id>:<run_id>''). Движок
alerting-engine, подписанный на этот канал, выполнит SQL правила в
StarRocks и обновит t_runs.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_trigger_rule(UUID) TO alerting_admin;

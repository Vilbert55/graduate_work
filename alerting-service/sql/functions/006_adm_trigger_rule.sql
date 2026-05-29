-- alerting.adm_trigger_rule — ручной запуск правила вне расписания.
--
-- На неделе 2 шлёт NOTIFY alerting_trigger с rule_id и возвращает новый
-- run_id. Реальный движок (неделя 3) будет слушать канал и выполнять SQL.
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

    -- Создаём pre-run запись со статусом skipped — движок (неделя 3)
    -- перепишет на running/success/failed при реальном исполнении.
    INSERT INTO alerting.t_runs(rule_id, status, error)
    VALUES (p_rule_id, 'skipped', 'TODO week3: engine not yet connected to NOTIFY channel')
    RETURNING id INTO v_run_id;

    PERFORM pg_notify('alerting_trigger', p_rule_id::text);

    RETURN v_run_id;
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_trigger_rule(UUID) IS
'Ручной запуск правила вне расписания. Возвращает run_id.

ВНИМАНИЕ: на неделе 2 функция шлёт NOTIFY alerting_trigger, но движок ещё
не подписан — фактического исполнения не происходит, в t_runs появляется
запись со статусом skipped. Реальное исполнение — неделя 3.';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_trigger_rule(UUID) TO alerting_admin;

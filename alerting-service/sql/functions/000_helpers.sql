-- Внутренние помощники схемы alerting. Загружаются первыми (префикс 000),
-- вызываются публичными adm_*-функциями. Роли alerting_admin не выдаются:
-- работают внутри SECURITY DEFINER-функций от имени владельца схемы.

-- Проверка канала доставки. NULL пропускается (в adm_update_rule NULL
-- означает «не менять»); невалидное непустое значение — ошибка.
CREATE OR REPLACE FUNCTION alerting._check_channel(p_channel TEXT)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    IF p_channel IS NOT NULL AND p_channel NOT IN ('email', 'ws') THEN
        RAISE EXCEPTION 'invalid_channel: %', p_channel;
    END IF;
END;
$$;

-- @statement

-- Грубая проверка cron: 5 полей через пробелы. NULL пропускается.
-- Полную валидацию делает движок (APScheduler CronTrigger.from_crontab).
CREATE OR REPLACE FUNCTION alerting._check_cron(p_cron TEXT)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    IF p_cron IS NOT NULL AND p_cron !~ '^\S+\s+\S+\s+\S+\s+\S+\s+\S+$' THEN
        RAISE EXCEPTION 'invalid_cron: %', p_cron;
    END IF;
END;
$$;

-- @statement

-- Поставить правило в очередь на исполнение движком: создать t_runs со
-- статусом 'running' и послать NOTIFY 'alerting_trigger' с пейлоадом
-- '<p_kind>:<rule_id>:<run_id>'. p_kind — 'trigger' (рассылка) или 'dryrun'
-- (тестовый прогон без рассылки). Возвращает run_id.
CREATE OR REPLACE FUNCTION alerting._enqueue_rule_run(p_rule_id UUID, p_kind TEXT)
RETURNS UUID
LANGUAGE plpgsql
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
        p_kind || ':' || p_rule_id::text || ':' || v_run_id::text);

    RETURN v_run_id;
END;
$$;

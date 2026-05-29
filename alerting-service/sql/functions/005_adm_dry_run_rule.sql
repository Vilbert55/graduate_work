-- alerting.adm_dry_run_rule — тестовый прогон правила без рассылки.
--
-- ВАЖНО: на неделе 2 функция возвращает заглушку (matched=0, after_cap=0).
-- Реальная логика выполнения SQL в StarRocks + применения лимита уведомлений
-- — задача недели 3 (выполняется alerting-engine).
--
-- Контракт результата зафиксирован сейчас, чтобы аналитик мог писать вызовы
-- уже на неделе 2 и они не сломались после подключения движка.
CREATE OR REPLACE FUNCTION alerting.adm_dry_run_rule(p_rule_id UUID)
RETURNS TABLE(matched INTEGER, after_cap INTEGER, sample UUID[])
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM alerting.t_rules
                    WHERE id = p_rule_id AND is_deleted = FALSE) THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_id;
    END IF;

    -- TODO неделя 3: вызвать движок (через NOTIFY/RPC), выполнить SQL,
    -- применить лимит уведомлений из frequency_cap, вернуть реальные числа.
    RETURN QUERY SELECT 0::INTEGER, 0::INTEGER, ARRAY[]::UUID[];
END;
$$;

-- @statement

COMMENT ON FUNCTION alerting.adm_dry_run_rule(UUID) IS
'Тестовый прогон правила: возвращает размер выборки до и после лимита
уведомлений + sample из нескольких user_id.

ВНИМАНИЕ: на неделе 2 — заглушка (всегда 0/0/{}). Реальная реализация —
неделя 3 (движок подключается к StarRocks, выполняет SQL, считает лимит).';

-- @statement

GRANT EXECUTE ON FUNCTION alerting.adm_dry_run_rule(UUID) TO alerting_admin;

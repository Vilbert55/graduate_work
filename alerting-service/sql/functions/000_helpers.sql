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

-- Статическая проверка SQL правила. Соединения Postgres -> StarRocks нет,
-- поэтому EXPLAIN здесь невозможен; проверяем только форму запроса: это запрос
-- на чтение (SELECT/WITH), один оператор, есть колонка user_id. Реальную
-- проверку исполнимости делает adm_dry_run_rule (движок реально выполняет SQL
-- под alert_reader). NULL пропускается (в adm_update_rule значит «не менять»).
CREATE OR REPLACE FUNCTION alerting._check_rule_sql(p_sql TEXT)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, alerting
AS $$
DECLARE
    v_sql TEXT := btrim(p_sql);
BEGIN
    IF p_sql IS NULL THEN
        RETURN;
    END IF;
    IF v_sql = '' THEN
        RAISE EXCEPTION 'invalid_sql: empty';
    END IF;
    IF v_sql !~* '^(select|with)\y' THEN
        RAISE EXCEPTION 'invalid_sql: query must start with SELECT or WITH';
    END IF;
    -- Точка с запятой не в самом конце = несколько операторов.
    IF rtrim(v_sql, E'; \n\t') ~ ';' THEN
        RAISE EXCEPTION 'invalid_sql: only a single statement is allowed';
    END IF;
    IF v_sql !~* 'user_id' THEN
        RAISE EXCEPTION 'invalid_sql: query must return column user_id';
    END IF;
END;
$$;

-- @statement

-- Проверка frequency_cap правила: это JSON-объект, единственный допустимый
-- ключ — per_rule_per_user_days (целое > 0). Общий дневной потолок на
-- пользователя задаётся настройкой движка ALERTING_GLOBAL_PER_USER_PER_DAY, а
-- не в правиле. NULL и пустой объект допустимы (лимит per-rule не задан).
CREATE OR REPLACE FUNCTION alerting._check_frequency_cap(p_cap JSONB)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, alerting
AS $$
DECLARE
    v_key TEXT;
    v_val JSONB;
BEGIN
    IF p_cap IS NULL THEN
        RETURN;
    END IF;
    IF jsonb_typeof(p_cap) <> 'object' THEN
        RAISE EXCEPTION 'invalid_frequency_cap: must be a JSON object';
    END IF;
    FOR v_key, v_val IN SELECT key, value FROM jsonb_each(p_cap) LOOP
        IF v_key = 'per_user_per_day' THEN
            RAISE EXCEPTION
                'invalid_frequency_cap: per_user_per_day is now a global engine setting (ALERTING_GLOBAL_PER_USER_PER_DAY), not a per-rule key';
        END IF;
        IF v_key <> 'per_rule_per_user_days' THEN
            RAISE EXCEPTION 'invalid_frequency_cap: unknown key "%", allowed: per_rule_per_user_days', v_key;
        END IF;
        IF jsonb_typeof(v_val) <> 'number' OR (v_val::numeric) <= 0
           OR (v_val::numeric) <> floor(v_val::numeric) THEN
            RAISE EXCEPTION 'invalid_frequency_cap: "%" must be a positive integer', v_key;
        END IF;
    END LOOP;
END;
$$;

-- @statement

-- Поставить правило в очередь на исполнение движком: создать t_runs со
-- статусом 'running' и послать NOTIFY 'alerting_trigger' с пейлоадом
-- '<p_kind>:<rule_id>:<run_id>'. p_kind — 'trigger' (рассылка) или 'dryrun'
-- (тестовый прогон без рассылки). is_dry_run помечает запуск, чтобы recovery
-- не «дослал» прерванный тестовый прогон реальными письмами. Возвращает run_id.
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

    INSERT INTO alerting.t_runs(rule_id, status, is_dry_run)
    VALUES (p_rule_id, 'running', p_kind = 'dryrun')
    RETURNING id INTO v_run_id;

    PERFORM pg_notify('alerting_trigger',
        p_kind || ':' || p_rule_id::text || ':' || v_run_id::text);

    RETURN v_run_id;
END;
$$;

-- @statement

-- Разрешает человекочитаемый code правила в его UUID. Это позволяет публичным
-- adm_*-функциям принимать code (его администратор и так держит в голове после
-- adm_create_rule), а не длинный uuid. code — глобально уникальный и неизменяемый
-- бизнес-ключ (uq_t_rules_code), поэтому однозначно адресует правило.
-- Мягко удалённые правила не находятся: их code занят, но операции над ними
-- бессмысленны — отдаём rule_not_found, как и раньше.
CREATE OR REPLACE FUNCTION alerting._rule_id(p_rule_code TEXT)
RETURNS UUID
LANGUAGE plpgsql
SET search_path = pg_catalog, alerting
AS $$
DECLARE
    v_rule_id UUID;
BEGIN
    SELECT id INTO v_rule_id
      FROM alerting.t_rules
     WHERE code = p_rule_code AND is_deleted = FALSE;

    IF v_rule_id IS NULL THEN
        RAISE EXCEPTION 'rule_not_found: %', p_rule_code;
    END IF;

    RETURN v_rule_id;
END;
$$;

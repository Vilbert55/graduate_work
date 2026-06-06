-- alerting.maint_dispatch_partitions — обслуживание партиций t_dispatch_history.
-- Зовётся движком при старте и раз в сутки: нарезает партиции текущей и
-- следующей недели и дропает партиции старше retention. Вызывается владельцем
-- схемы (движок ходит под postgres) — роли alerting_admin не выдаётся.
--
-- Партиция называется по понедельнику своей ISO-недели
-- (t_dispatch_history_pYYYYMMDD): имя однозначно кодирует диапазон недели и
-- легко парсится обратно для retention.
CREATE OR REPLACE FUNCTION alerting.maint_dispatch_partitions(p_retention_days INTEGER DEFAULT 90)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, alerting
AS $$
DECLARE
    v_week_start DATE;
    v_part_name  TEXT;
    v_cutoff     DATE := ((now() AT TIME ZONE 'utc')::date - p_retention_days);
    i            INTEGER;
    r            RECORD;
BEGIN
    -- 1. Гарантируем партиции на текущую и следующую неделю (идемпотентно).
    FOR i IN 0..1 LOOP
        v_week_start := date_trunc('week', (now() AT TIME ZONE 'utc')::date)::date + (i * 7);
        v_part_name  := 't_dispatch_history_p' || to_char(v_week_start, 'YYYYMMDD');
        IF to_regclass('alerting.' || v_part_name) IS NULL THEN
            EXECUTE format(
                'CREATE TABLE alerting.%I PARTITION OF alerting.t_dispatch_history '
                'FOR VALUES FROM (%L) TO (%L)',
                v_part_name, v_week_start, v_week_start + 7
            );
        END IF;
    END LOOP;

    -- 2. Retention: дропаем партиции, чей конец недели уже старше cutoff.
    FOR r IN
        SELECT c.relname
        FROM pg_inherits inh
        JOIN pg_class c     ON c.oid = inh.inhrelid
        JOIN pg_class p     ON p.oid = inh.inhparent
        JOIN pg_namespace n ON n.oid = p.relnamespace
        WHERE n.nspname = 'alerting' AND p.relname = 't_dispatch_history'
          AND c.relname ~ '^t_dispatch_history_p[0-9]{8}$'
    LOOP
        IF to_date(right(r.relname, 8), 'YYYYMMDD') + 7 <= v_cutoff THEN
            EXECUTE format('DROP TABLE alerting.%I', r.relname);
        END IF;
    END LOOP;
END;
$$;

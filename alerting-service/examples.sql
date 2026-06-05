-- Шпаргалка аналитика. Открывать в DBeaver под пользователем с ролью alerting_admin.
-- Создание пользователя (от postgres):
--     CREATE USER alerting_admin_ivanov WITH PASSWORD 'strong';
--     GRANT alerting_admin TO alerting_admin_ivanov;

-- ============================================================
-- 1. Тестируем выборку в StarRocks (отдельным подключением DBeaver,
--    через MySQL-driver localhost:9030 / alert_reader).
-- ============================================================

-- USE ugc_analytics;
-- SELECT user_id,
--        to_json(named_struct('top_genres', t.top_genres)) AS context
-- FROM ugc_analytics.mv_user_activity a
-- JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
-- WHERE a.was_active_last_month = TRUE
--   AND a.last_watch_at < now() - INTERVAL 7 DAY;

-- ============================================================
-- 2. Регистрируем правило в Postgres.
-- ============================================================
SELECT alerting.adm_create_rule(
    p_code          := 'winback_active_user',
    p_description   := 'Возврат угасших активных зрителей',
    p_sql           := $sql$
        SELECT user_id,
               to_json(named_struct('top_genres', t.top_genres)) AS context
        FROM ugc_analytics.mv_user_activity a
        JOIN ugc_analytics.mv_user_top_genres t USING (user_id)
        WHERE a.was_active_last_month = TRUE
          AND a.last_watch_at < now() - INTERVAL 7 DAY
        $sql$,
    p_cron          := '0 9 * * *',                      -- каждое утро в 9:00 UTC
    p_template_code := 'winback_recommendation',
    p_channel       := 'email',
    p_frequency_cap := '{"per_rule_per_user_days": 30, "per_user_per_day": 1}'::jsonb,
    p_max_users     := 50000
);

-- ============================================================
-- 3. Dry-run: выполнить SQL в StarRocks, посчитать аудиторию, БЕЗ рассылки.
--    Функция возвращает run_id; результат — в v_runs.
-- ============================================================
-- Все adm_*-функции адресуют правило по его code (тот же, что в adm_create_rule),
-- искать uuid вручную не нужно.
SELECT alerting.adm_dry_run_rule('winback_active_user') AS run_id;
\gset

-- Подождать 1-2 секунды, потом посмотреть:
SELECT status, matched_users, after_cap_users, error
FROM alerting.v_runs
WHERE run_id = :'run_id';

-- ============================================================
-- 4. Включаем / выключаем / удаляем правило.
-- ============================================================
SELECT alerting.adm_enable_rule('winback_active_user');
SELECT alerting.adm_disable_rule('winback_active_user');
SELECT alerting.adm_delete_rule('winback_active_user');

-- ============================================================
-- 5. Ручной запуск вне расписания.
-- ============================================================
SELECT alerting.adm_trigger_rule('winback_active_user');

-- ============================================================
-- 6. Мониторинг.
-- ============================================================
SELECT * FROM alerting.v_rules    ORDER BY next_run_at;
SELECT * FROM alerting.v_runs     ORDER BY started_at DESC LIMIT 50;
SELECT * FROM alerting.v_dispatch ORDER BY sent_at DESC LIMIT 50;

-- ============================================================
-- 7. Принудительная синхронизация dim_*-таблиц StarRocks
--    (для демо: вместо ожидания часового SCHEDULE).
--    Выполнять под root через MySQL-протокол StarRocks.
--    NB: StarRocks 4.0.8 НЕ поддерживает `EXECUTE TASK <name>` —
--    для ручного прогона повторяем тот же INSERT OVERWRITE, что и в SUBMIT TASK.
-- ============================================================
-- USE ugc_analytics;
-- INSERT OVERWRITE dim_users
-- SELECT CAST(u.id AS VARCHAR(36)), u.gender, u.age, u.country,
--        concat_ws('_', coalesce(u.gender,'X'),
--            CASE WHEN u.age IS NULL THEN 'X'
--                 WHEN u.age < 18  THEN '0-17'  WHEN u.age <= 24 THEN '18-24'
--                 WHEN u.age <= 34 THEN '25-34' WHEN u.age <= 44 THEN '35-44'
--                 WHEN u.age <= 54 THEN '45-54' ELSE '55+' END,
--            coalesce(u.country,'X')),
--        u.created_at, u.is_demo
-- FROM pg_catalog.auth.users u;
-- -- (dim_films / dim_genres / dim_date — аналогично, см. starrocks_dims_init/init.sql)
-- REFRESH MATERIALIZED VIEW mv_user_activity        WITH SYNC MODE;
-- REFRESH MATERIALIZED VIEW mv_user_top_genres      WITH SYNC MODE;
-- REFRESH MATERIALIZED VIEW mv_segment_film_activity WITH SYNC MODE;
-- REFRESH MATERIALIZED VIEW mv_film_watch_hourly    WITH SYNC MODE;
-- REFRESH MATERIALIZED VIEW mv_weekend_film_activity WITH SYNC MODE;

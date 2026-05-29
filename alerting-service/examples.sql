-- Шпаргалка аналитика. Открывать в DBeaver под пользователем с ролью alerting_admin.
-- Создание пользователя (от postgres):
--     CREATE USER alerting_admin_ivanov WITH PASSWORD 'strong';
--     GRANT alerting_admin TO alerting_admin_ivanov;

-- ============================================================
-- 1. Тестируем выборку в StarRocks (отдельным подключением DBeaver,
--    через MySQL-driver localhost:9030 / alert_reader).
-- ============================================================

-- USE ugc_analytics;
-- SELECT user_id, json_object('top_genres', top_genres) AS context
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
               json_object('top_genres', t.top_genres) AS context
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
SELECT alerting.adm_dry_run_rule(
    (SELECT id FROM alerting.t_rules WHERE code = 'winback_active_user')
) AS run_id;
\gset

-- Подождать 1-2 секунды, потом посмотреть:
SELECT status, matched_users, after_cap_users, error
FROM alerting.v_runs
WHERE run_id = :'run_id';

-- ============================================================
-- 4. Включаем / выключаем / удаляем правило.
-- ============================================================
SELECT alerting.adm_enable_rule((SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));
SELECT alerting.adm_disable_rule((SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));
SELECT alerting.adm_delete_rule((SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));

-- ============================================================
-- 5. Ручной запуск вне расписания.
-- ============================================================
SELECT alerting.adm_trigger_rule((SELECT id FROM alerting.t_rules WHERE code='winback_active_user'));

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
-- ============================================================
-- USE ugc_analytics;
-- EXECUTE TASK sync_dim_users;
-- EXECUTE TASK sync_dim_films;
-- EXECUTE TASK sync_dim_genres;
-- EXECUTE TASK sync_dim_date;
-- REFRESH MATERIALIZED VIEW mv_user_activity;
-- REFRESH MATERIALIZED VIEW mv_user_top_genres;
-- REFRESH MATERIALIZED VIEW mv_segment_film_activity;
-- REFRESH MATERIALIZED VIEW mv_film_watch_hourly;
-- REFRESH MATERIALIZED VIEW mv_weekend_film_activity;

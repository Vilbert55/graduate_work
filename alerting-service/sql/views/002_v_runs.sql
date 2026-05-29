-- alerting.v_runs — история срабатываний правила.
CREATE OR REPLACE VIEW alerting.v_runs AS
SELECT
    ru.id              AS run_id,
    ru.rule_id,
    r.code             AS rule_code,
    ru.started_at,
    ru.finished_at,
    ru.duration_ms,
    ru.matched_users,
    ru.after_cap_users,
    ru.dispatched_users,
    ru.notification_task_id,
    ru.status,
    ru.error
FROM alerting.t_runs ru
JOIN alerting.t_rules r ON r.id = ru.rule_id;

-- @statement

COMMENT ON VIEW alerting.v_runs IS
'История срабатываний правил: время, длительность, размеры выборки до/после
лимита уведомлений, статус, ошибка. Доступно роли alerting_admin.';

-- @statement

GRANT SELECT ON alerting.v_runs TO alerting_admin;

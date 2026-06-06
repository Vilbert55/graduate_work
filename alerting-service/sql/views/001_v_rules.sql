-- alerting.v_rules — каталог правил со статусом и счётчиком отправок за 24 часа.
CREATE OR REPLACE VIEW alerting.v_rules AS
SELECT
    r.id,
    r.code,
    r.description,
    CASE
        WHEN NOT r.is_enabled THEN 'disabled'
        WHEN r.status = 'invalid' THEN 'invalid'
        ELSE 'active'
    END AS status,
    r.cron_expression,
    r.template_code,
    r.channel,
    r.frequency_cap,
    r.max_users,
    r.last_run_at,
    r.next_run_at,
    r.last_validation_error,
    (
        SELECT count(*)::int
        FROM alerting.t_dispatch_history d
        WHERE d.rule_id = r.id
          AND d.sent_at > (now() AT TIME ZONE 'utc') - INTERVAL '24 hours'
    ) AS sent_last_24h,
    r.created_by,
    r.created_at,
    r.updated_at
FROM alerting.t_rules r;

-- @statement

COMMENT ON VIEW alerting.v_rules IS
'Каталог правил со статусом (active/disabled/invalid), расписанием,
шаблоном и числом отправок за последние 24 часа. Доступно роли alerting_admin.';

-- @statement

GRANT SELECT ON alerting.v_rules TO alerting_admin;

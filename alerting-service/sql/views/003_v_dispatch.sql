-- alerting.v_dispatch — история доставки конкретным пользователям (аудит, разбор жалоб).
CREATE OR REPLACE VIEW alerting.v_dispatch AS
SELECT
    d.rule_id,
    r.code AS rule_code,
    d.user_id,
    d.channel,
    d.sent_at
FROM alerting.t_dispatch_history d
JOIN alerting.t_rules r ON r.id = d.rule_id;

-- @statement

COMMENT ON VIEW alerting.v_dispatch IS
'Журнал отправок: какому пользователю и каким правилом было отправлено
уведомление. Используется для разбора жалоб. Доступно роли alerting_admin.';

-- @statement

GRANT SELECT ON alerting.v_dispatch TO alerting_admin;

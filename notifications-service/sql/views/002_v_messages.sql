-- notifications.v_messages — представление для администратора: журнал сообщений.
-- Открывать в DBeaver под пользователем с ролью notification_admin.
CREATE OR REPLACE VIEW notifications.v_messages AS
SELECT
    m.id,
    m.task_id,
    m.user_id,
    m.channel,
    m.recipient_address,
    m.status,
    m.attempts,
    m.subject,
    m.body_format,
    m.created_at,
    m.queued_at,
    m.sent_at,
    m.next_attempt_at,
    m.last_error,
    t.name AS task_name
FROM notifications.t_messages m
LEFT JOIN notifications.t_tasks t ON t.id = m.task_id;

-- @statement

COMMENT ON VIEW notifications.v_messages IS
'Журнал сообщений: статусы, попытки, ошибки. Доступно роли notification_admin.
Колонка body намеренно исключена — для просмотра тела использовать _get_messages_for_user.';

-- @statement

GRANT SELECT ON notifications.v_messages TO notification_admin;

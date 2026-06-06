-- notifications.v_tasks — представление для администратора:
-- задания на рассылку с раскрытым кодом и именем шаблона.
-- Открывать в DBeaver под пользователем с ролью notification_admin.
CREATE OR REPLACE VIEW notifications.v_tasks AS
SELECT
    t.id,
    t.code,
    t.name,
    t.is_enabled,
    t.channel,
    tp.code        AS template_code,
    tp.name        AS template_name,
    t.audience,
    t.params,
    t.cron_expression,
    t.start_at,
    t.end_at,
    t.last_run_at,
    t.next_run_at,
    t.created_by,
    t.idempotency_key,
    t.created_at,
    t.updated_at
FROM notifications.t_tasks t
JOIN notifications.t_templates tp ON tp.id = t.template_id;

-- @statement

COMMENT ON VIEW notifications.v_tasks IS
'Задания на рассылку с раскрытым шаблоном. Доступно роли notification_admin.
Колонка code — бизнес-ключ задания, по нему ведётся управление.
Для изменений использовать: adm_create_task, adm_update_task(code), adm_enable_task(code), adm_disable_task(code).';

-- @statement

GRANT SELECT ON notifications.v_tasks TO notification_admin;

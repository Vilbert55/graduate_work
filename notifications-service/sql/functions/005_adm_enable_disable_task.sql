-- notifications.adm_enable_task / adm_disable_task — переключатели задания.
-- Вызываются администратором из DBeaver.

CREATE OR REPLACE FUNCTION notifications.adm_enable_task(p_task_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
BEGIN
    UPDATE notifications.t_tasks
    SET is_enabled = TRUE,
        updated_at = (now() AT TIME ZONE 'utc')
    WHERE id = p_task_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'task_not_found: %', p_task_id;
    END IF;
END;
$$;

-- @statement

CREATE OR REPLACE FUNCTION notifications.adm_disable_task(p_task_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
BEGIN
    UPDATE notifications.t_tasks
    SET is_enabled = FALSE,
        updated_at = (now() AT TIME ZONE 'utc')
    WHERE id = p_task_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'task_not_found: %', p_task_id;
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.adm_enable_task(UUID) IS
'Включить задание на рассылку (устанавливает is_enabled = TRUE).

Аргументы:
  p_task_id UUID — идентификатор задания

Выбрасывает исключение task_not_found если задание не существует.';

-- @statement

COMMENT ON FUNCTION notifications.adm_disable_task(UUID) IS
'Отключить задание на рассылку (устанавливает is_enabled = FALSE).
Уже созданные сообщения (t_messages) продолжают обрабатываться и доставляться.

Аргументы:
  p_task_id UUID — идентификатор задания

Выбрасывает исключение task_not_found если задание не существует.';

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_enable_task(UUID) TO notification_admin;

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_disable_task(UUID) TO notification_admin;

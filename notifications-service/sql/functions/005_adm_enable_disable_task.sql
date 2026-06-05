-- notifications.adm_enable_task / adm_disable_task — переключатели задания.
-- Вызываются администратором из DBeaver.

CREATE OR REPLACE FUNCTION notifications.adm_enable_task(p_task_code TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
BEGIN
    UPDATE notifications.t_tasks
    SET is_enabled = TRUE,
        updated_at = (now() AT TIME ZONE 'utc')
    WHERE id = notifications._task_id(p_task_code);
END;
$$;

-- @statement

CREATE OR REPLACE FUNCTION notifications.adm_disable_task(p_task_code TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, notifications
AS $$
BEGIN
    UPDATE notifications.t_tasks
    SET is_enabled = FALSE,
        updated_at = (now() AT TIME ZONE 'utc')
    WHERE id = notifications._task_id(p_task_code);
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.adm_enable_task(TEXT) IS
'Включить задание на рассылку по code (устанавливает is_enabled = TRUE).

Аргументы:
  p_task_code TEXT — бизнес-ключ задания (t_tasks.code)

Выбрасывает исключение task_not_found если задание с таким code не существует.';

-- @statement

COMMENT ON FUNCTION notifications.adm_disable_task(TEXT) IS
'Отключить задание на рассылку по code (устанавливает is_enabled = FALSE).
Уже созданные сообщения (t_messages) продолжают обрабатываться и доставляться.

Аргументы:
  p_task_code TEXT — бизнес-ключ задания (t_tasks.code)

Выбрасывает исключение task_not_found если задание с таким code не существует.';

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_enable_task(TEXT) TO notification_admin;

-- @statement

GRANT EXECUTE ON FUNCTION notifications.adm_disable_task(TEXT) TO notification_admin;

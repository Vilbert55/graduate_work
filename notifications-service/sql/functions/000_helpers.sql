-- Внутренние помощники схемы notifications. Загружаются первыми (префикс 000),
-- вызываются публичными adm_*-функциями. Роли notification_admin не выдаются:
-- работают внутри SECURITY DEFINER-функций от имени владельца схемы.

-- Разрешает человекочитаемый code задания в его UUID. Это позволяет
-- административным adm_*_task-функциям принимать code (тот же, что задаётся в
-- adm_create_task), а не длинный uuid. code — уникальный бизнес-ключ задания
-- (uq_t_tasks_code). Задания без code (одноразовые/программные рассылки) этими
-- ручками не управляются — для них code не задаётся.
CREATE OR REPLACE FUNCTION notifications._task_id(p_task_code TEXT)
RETURNS UUID
LANGUAGE plpgsql
SET search_path = pg_catalog, notifications
AS $$
DECLARE
    v_task_id UUID;
BEGIN
    IF p_task_code IS NULL THEN
        RAISE EXCEPTION 'task_code_required';
    END IF;

    SELECT id INTO v_task_id
      FROM notifications.t_tasks
     WHERE code = p_task_code;

    IF v_task_id IS NULL THEN
        RAISE EXCEPTION 'task_not_found: %', p_task_code;
    END IF;

    RETURN v_task_id;
END;
$$;

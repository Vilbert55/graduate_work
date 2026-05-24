-- Групповая роль для администратора уведомлений.
-- Реальный пользователь создаётся отдельно (см. README) и получает эту роль через GRANT.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notification_admin') THEN
        CREATE ROLE notification_admin;
    END IF;
END;
$$;

-- @statement

GRANT USAGE ON SCHEMA notifications TO notification_admin;

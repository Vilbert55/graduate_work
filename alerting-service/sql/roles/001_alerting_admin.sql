-- Групповая роль для администратора правил alerting.
-- Реальный пользователь создаётся отдельно (см. README) и получает её через GRANT.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alerting_admin') THEN
        CREATE ROLE alerting_admin;
    END IF;
END;
$$;

-- @statement

GRANT USAGE ON SCHEMA alerting TO alerting_admin;

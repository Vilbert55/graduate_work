-- notifications.svc_get_messages_for_user — выдача пользователю его уведомлений.
-- Предназначена для вызова из API-сервиса (личный кабинет).
CREATE OR REPLACE FUNCTION notifications.svc_get_messages_for_user(
    p_user_id UUID,
    p_limit   INT DEFAULT 50
) RETURNS TABLE(
    id         UUID,
    channel    TEXT,
    subject    TEXT,
    body       TEXT,
    body_format TEXT,
    status     TEXT,
    sent_at    TIMESTAMP,
    created_at TIMESTAMP
)
LANGUAGE sql
STABLE
AS $$
    SELECT id, channel::TEXT, subject, body, body_format::TEXT,
           status::TEXT, sent_at, created_at
    FROM notifications.t_messages
    WHERE user_id = p_user_id
    ORDER BY created_at DESC
    LIMIT p_limit;
$$;

-- @statement

COMMENT ON FUNCTION notifications.svc_get_messages_for_user(UUID, INT) IS
'Список уведомлений пользователя для API личного кабинета.
Предназначена для вызова из API-сервиса; не предназначена для прямого вызова администратором
(для мониторинга использовать представление v_messages).

Аргументы:
  p_user_id UUID       — идентификатор пользователя
  p_limit   INT DEFAULT 50 — максимальное число записей; сортировка: новые первыми

Возвращает набор строк: id, channel, subject, body, body_format, status, sent_at, created_at.';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications.svc_get_messages_for_user(UUID, INT) FROM PUBLIC;

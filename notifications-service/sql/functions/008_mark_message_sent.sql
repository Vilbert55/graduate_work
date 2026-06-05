-- notifications._mark_message_sent — sender: финальный успех доставки.
-- Вызывается только воркерами email-sender и ws-gateway.
CREATE OR REPLACE FUNCTION notifications._mark_message_sent(
    p_message_id UUID,
    p_worker_id  TEXT DEFAULT NULL
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE notifications.t_messages
    SET status          = 'sent',
        sent_at         = (now() AT TIME ZONE 'utc'),
        last_error      = NULL,
        next_attempt_at = NULL
    WHERE id = p_message_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'message_not_found: %', p_message_id;
    END IF;

    IF p_worker_id IS NOT NULL THEN
        INSERT INTO notifications.t_worker_lease_log(worker_id, operation, message_id)
        VALUES (p_worker_id, 'sent', p_message_id);
    END IF;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications._mark_message_sent(UUID, TEXT) IS
'Sender: пометить сообщение как успешно доставленное (статус -> sent).
Предназначена для вызова только воркерами email-sender и ws-gateway.
Идемпотентна: повторный вызов перепишет sent_at, что безвредно.

Аргументы:
  p_message_id UUID        — идентификатор сообщения
  p_worker_id  TEXT DEFAULT NULL — идентификатор воркера для журнала t_worker_lease_log;
                                   NULL — запись в журнал не создаётся

Выбрасывает исключение message_not_found если запись отсутствует.';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications._mark_message_sent(UUID, TEXT) FROM PUBLIC;

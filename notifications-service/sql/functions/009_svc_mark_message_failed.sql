-- notifications.svc_mark_message_failed — sender: обработка ошибки доставки.
-- При attempts >= p_max_attempts -> статус 'dead' (сообщение покидает систему).
-- Иначе -> 'pending' + next_attempt_at с экспоненциальным backoff (30s * 2^attempts).
-- Вызывается только воркерами email-sender и ws-gateway.
CREATE OR REPLACE FUNCTION notifications.svc_mark_message_failed(
    p_message_id  UUID,
    p_error       TEXT,
    p_max_attempts INT  DEFAULT 5,
    p_worker_id   TEXT DEFAULT NULL
) RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
    cur_attempts INT;
    new_status   TEXT;
BEGIN
    SELECT attempts INTO cur_attempts
    FROM notifications.t_messages
    WHERE id = p_message_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'message_not_found: %', p_message_id;
    END IF;

    IF cur_attempts >= p_max_attempts THEN
        new_status := 'dead';
        UPDATE notifications.t_messages
        SET status          = 'dead',
            last_error      = p_error,
            next_attempt_at = NULL
        WHERE id = p_message_id;
    ELSE
        new_status := 'pending';
        UPDATE notifications.t_messages
        SET status          = 'pending',
            last_error      = p_error,
            -- задержки: 30s, 60s, 120s, 240s, 480s
            next_attempt_at = (now() AT TIME ZONE 'utc')
                + make_interval(secs => 30 * power(2, cur_attempts)::INT)
        WHERE id = p_message_id;
    END IF;

    IF p_worker_id IS NOT NULL THEN
        INSERT INTO notifications.t_worker_lease_log(worker_id, operation, message_id, note)
        VALUES (p_worker_id, 'failed:' || new_status, p_message_id, left(p_error, 255));
    END IF;

    RETURN new_status;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.svc_mark_message_failed(UUID, TEXT, INT, TEXT) IS
'Sender: зафиксировать ошибку доставки и вычислить следующий шаг.
Предназначена для вызова только воркерами email-sender и ws-gateway.

Аргументы:
  p_message_id   UUID        — идентификатор сообщения
  p_error        TEXT        — текст ошибки (обрезается до 255 символов в журнале)
  p_max_attempts INT DEFAULT 5 — максимальное число попыток; при превышении -> dead
  p_worker_id    TEXT DEFAULT NULL — идентификатор воркера для t_worker_lease_log

Возвращает TEXT: ''pending'' (будет повторная попытка) или ''dead'' (финал).

Backoff: next_attempt_at = now() + 30s * 2^(текущее_число_попыток).
  Попытка 1 -> 30 с, 2 -> 60 с, 3 -> 120 с, 4 -> 240 с, 5 -> 480 с.

Выбрасывает исключение message_not_found если запись отсутствует.';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications.svc_mark_message_failed(UUID, TEXT, INT, TEXT) FROM PUBLIC;

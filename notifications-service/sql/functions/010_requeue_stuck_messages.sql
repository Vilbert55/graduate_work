-- notifications._requeue_stuck_messages — recovery worker:
-- возвращает в pending сообщения, застрявшие в queued/sending дольше таймаутов.
-- Причины: упал publisher, упал sender, сообщение потеряно в RabbitMQ.
-- Вызывается только воркером recovery.
CREATE OR REPLACE FUNCTION notifications._requeue_stuck_messages(
    p_queued_timeout_sec  INT  DEFAULT 300,
    p_sending_timeout_sec INT  DEFAULT 600,
    p_worker_id           TEXT DEFAULT 'recovery'
) RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INT;
    v_now   TIMESTAMP := (now() AT TIME ZONE 'utc');
BEGIN
    WITH stuck AS (
        SELECT id, status
        FROM notifications.t_messages
        WHERE
            (status = 'queued'
             AND queued_at < v_now - make_interval(secs => p_queued_timeout_sec))
            OR
            (status = 'sending'
             AND queued_at IS NOT NULL
             AND queued_at < v_now - make_interval(secs => p_sending_timeout_sec))
        FOR UPDATE SKIP LOCKED
    ),
    upd AS (
        UPDATE notifications.t_messages m
        SET status          = 'pending',
            next_attempt_at = NULL,
            last_error      = COALESCE(m.last_error, '')
                              || ' [recovery: stuck from ' || stuck.status || ']'
        FROM stuck
        WHERE m.id = stuck.id
        RETURNING m.id
    ),
    log_entry AS (
        INSERT INTO notifications.t_worker_lease_log(worker_id, operation, message_id)
        SELECT p_worker_id, 'recovery_requeue', upd.id FROM upd
        RETURNING 1
    )
    SELECT COUNT(*) INTO v_count FROM upd;

    RETURN v_count;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications._requeue_stuck_messages(INT, INT, TEXT) IS
'Recovery worker: возврат в pending сообщений, застрявших в queued или sending.
Предназначена для вызова только воркером recovery.

Аргументы:
  p_queued_timeout_sec  INT  DEFAULT 300  — порог для queued-сообщений (секунды с момента queued_at)
  p_sending_timeout_sec INT  DEFAULT 600  — порог для sending-сообщений (секунды с момента queued_at)
  p_worker_id           TEXT DEFAULT ''recovery'' — идентификатор воркера для t_worker_lease_log

Возвращает INT: число переведённых в pending сообщений.

Типичные причины застревания:
  queued  — publisher упал после commit, но до publish в RabbitMQ
  sending — sender упал после mark_message_sending, но до mark_message_sent';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications._requeue_stuck_messages(INT, INT, TEXT) FROM PUBLIC;

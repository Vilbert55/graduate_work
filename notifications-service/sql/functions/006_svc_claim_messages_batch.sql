-- notifications.svc_claim_messages_batch — outbox publisher:
-- атомарно забирает порцию pending-сообщений и переводит их в queued.
-- Вызывается только воркером publisher.
CREATE OR REPLACE FUNCTION notifications.svc_claim_messages_batch(
    p_worker_id  TEXT,
    p_batch_size INT DEFAULT 100
) RETURNS TABLE(
    message_id UUID,
    channel    TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    WITH claimed AS (
        SELECT id
        FROM notifications.t_messages
        WHERE status = 'pending'
          AND (next_attempt_at IS NULL
               OR next_attempt_at <= (now() AT TIME ZONE 'utc'))
        ORDER BY COALESCE(next_attempt_at, created_at)
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED
    ),
    upd AS (
        UPDATE notifications.t_messages m
        SET status    = 'queued',
            queued_at = (now() AT TIME ZONE 'utc'),
            next_attempt_at = NULL
        FROM claimed
        WHERE m.id = claimed.id
        RETURNING m.id, m.channel
    ),
    log_entry AS (
        INSERT INTO notifications.t_worker_lease_log(worker_id, operation, message_id)
        SELECT p_worker_id, 'claim', upd.id FROM upd
        RETURNING 1
    )
    SELECT u.id, u.channel::TEXT FROM upd u;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications.svc_claim_messages_batch(TEXT, INT) IS
'Outbox publisher: атомарный SELECT FOR UPDATE SKIP LOCKED + перевод pending -> queued.
Предназначена для вызова только воркером publisher.

Аргументы:
  p_worker_id  TEXT       — идентификатор воркера для журнала (формат: ''publisher@host:pid'')
  p_batch_size INT DEFAULT 100 — максимальное число сообщений за один вызов

Возвращает набор строк (message_id UUID, channel TEXT).';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications.svc_claim_messages_batch(TEXT, INT) FROM PUBLIC;

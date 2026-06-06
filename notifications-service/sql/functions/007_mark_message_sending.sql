-- notifications._mark_message_sending — sender: атомарно проверяет статус,
-- блокирует строку, переводит в 'sending', возвращает payload для отправки.
-- Вызывается воркерами email-sender и ws-gateway.
--
-- Поля is_already_sent / is_dead сигнализируют consumer-у о нужном действии:
--   is_already_sent = TRUE -> ack без работы (защита от дубликата из RabbitMQ)
--   is_dead         = TRUE -> ack без работы (превышено число попыток)
--   оба FALSE              -> можно отправлять (payload заполнен)
--
-- OUT-параметры с префиксом out_ — чтобы избежать конфликта имён
-- с колонками t_messages при чтении внутри функции.
CREATE OR REPLACE FUNCTION notifications._mark_message_sending(
    p_message_id UUID
) RETURNS TABLE(
    is_already_sent      BOOLEAN,
    is_dead              BOOLEAN,
    out_attempts         INT,
    out_channel          TEXT,
    out_user_id          UUID,
    out_subject          TEXT,
    out_body             TEXT,
    out_body_format      TEXT,
    out_recipient_address TEXT
)
LANGUAGE plpgsql
AS $$
DECLARE
    rec RECORD;
BEGIN
    -- FOR UPDATE: сериализует параллельных sender-ов; второй увидит актуальный статус.
    SELECT * INTO rec
    FROM notifications.t_messages
    WHERE id = p_message_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'message_not_found: %', p_message_id;
    END IF;

    IF rec.status = 'sent' THEN  -- дубль AMQP-сообщения: уже доставлено
        RETURN QUERY SELECT TRUE, FALSE, rec.attempts,
            rec.channel::TEXT, rec.user_id, rec.subject, rec.body,
            rec.body_format::TEXT, rec.recipient_address::TEXT;
        RETURN;
    END IF;

    IF rec.status = 'dead' THEN
        RETURN QUERY SELECT FALSE, TRUE, rec.attempts,
            rec.channel::TEXT, rec.user_id, rec.subject, rec.body,
            rec.body_format::TEXT, rec.recipient_address::TEXT;
        RETURN;
    END IF;

    UPDATE notifications.t_messages
    SET status   = 'sending',
        attempts = t_messages.attempts + 1
    WHERE id = p_message_id;

    RETURN QUERY SELECT FALSE, FALSE, rec.attempts + 1,
        rec.channel::TEXT, rec.user_id, rec.subject, rec.body,
        rec.body_format::TEXT, rec.recipient_address::TEXT;
END;
$$;

-- @statement

COMMENT ON FUNCTION notifications._mark_message_sending(UUID) IS
'Sender: проверка идемпотентности + перевод сообщения в статус sending.
Предназначена для вызова только воркерами email-sender и ws-gateway.

Аргументы:
  p_message_id UUID — идентификатор сообщения из t_messages

Возвращает одну строку:
  is_already_sent BOOL — TRUE если сообщение уже было отправлено (ack без работы)
  is_dead         BOOL — TRUE если превышено число попыток (ack без работы)
  out_attempts    INT  — текущее число попыток (после инкремента)
  out_channel     TEXT — канал доставки: ''email'' | ''ws''
  out_user_id     UUID — получатель
  out_subject     TEXT — тема сообщения
  out_body        TEXT — тело сообщения
  out_body_format TEXT — формат тела: ''text'' | ''html''
  out_recipient_address TEXT — email-адрес (NULL для ws-канала)

Выбрасывает исключение message_not_found если запись отсутствует.';

-- @statement

REVOKE EXECUTE ON FUNCTION notifications._mark_message_sending(UUID) FROM PUBLIC;

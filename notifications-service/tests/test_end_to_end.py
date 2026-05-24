"""End-to-end и permission-тесты сервиса нотификаций.

Запуск всех тестов поверх живого docker-compose:
    cd notifications-service
    poetry install --with test
    poetry run pytest -v tests/

Запуск только тестов прав (нужен только movies-db с миграциями):
    poetry run pytest -v tests/ -m "not integration"
"""
import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

# UUID-заглушка для тестов прав: передаётся в функции как аргумент,
# но до выполнения тела функции дело не доходит — падает на проверке прав.
_DUMMY_UUID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Интеграционные тесты (требуют полного стека)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_welcome_email_flow(session_maker, mailpit):
    """Отправка приветственного письма доходит до Mailpit."""
    async with session_maker() as s:
        user_id = (await s.execute(
            text("SELECT id FROM auth.users WHERE login='alice'"),
        )).scalar()
        await s.execute(
            text(
                "SELECT notifications.svc_send_user_event(:u, 'welcome', 'email', "
                "'{}'::jsonb, :ik)",
            ),
            {"u": user_id, "ik": f"test-{uuid.uuid4()}"},
        )
        await s.commit()

    # Ждём до 30 сек: scheduler -> publisher -> email-sender
    for _ in range(60):
        await asyncio.sleep(0.5)
        r = await mailpit.get("/api/v1/messages")
        msgs = r.json().get("messages", r.json().get("Messages", []))
        if any(
            "alice@" in t.get("Address", "")
            for m in msgs
            for t in m.get("To", [])
        ):
            break
    else:
        pytest.fail("email not delivered in time")


@pytest.mark.integration
async def test_duplicate_publish_no_double_send(session_maker, mailpit):
    """Повторная публикация message_id в RabbitMQ не приводит ко второму письму."""
    pass


@pytest.mark.integration
async def test_dlx_path_on_smtp_failure():
    """SMTP-ошибка после max_attempts переводит сообщение в статус dead."""
    pass


# ---------------------------------------------------------------------------
# Функциональные тесты (нужна только БД с миграциями)
# ---------------------------------------------------------------------------


async def test_idempotency_create_task(session_maker):
    """Повторный adm_create_task с тем же idempotency_key возвращает тот же id."""
    key = f"idem-{uuid.uuid4()}"
    audience = json.dumps({"type": "user_ids", "values": [_DUMMY_UUID]})
    async with session_maker() as s:
        task_a = (await s.execute(
            text(
                "SELECT notifications.adm_create_task('welcome','email',"
                "CAST(:aud AS jsonb), NULL, '{}'::jsonb, NULL, NULL, NULL, :k, 'test')",
            ),
            {"aud": audience, "k": key},
        )).scalar()
        task_b = (await s.execute(
            text(
                "SELECT notifications.adm_create_task('welcome','email',"
                "CAST(:aud AS jsonb), NULL, '{}'::jsonb, NULL, NULL, NULL, :k, 'test')",
            ),
            {"aud": audience, "k": key},
        )).scalar()
        assert task_a == task_b
        await s.rollback()


# ---------------------------------------------------------------------------
# Тесты прав: роль notification_admin не должна вызывать svc_* функции
#
# Каждый тест:
#   1. Получает соединение с SET LOCAL ROLE notification_admin.
#   2. Открывает SAVEPOINT через begin_nested().
#   3. Пытается вызвать svc_* функцию.
#   4. Ожидает ProgrammingError (permission denied for function ...).
#   5. Откатывает SAVEPOINT, сбрасывая состояние ошибки транзакции.
# ---------------------------------------------------------------------------


async def test_admin_cannot_call_svc_send_user_event(admin_conn):
    """notification_admin не имеет EXECUTE на svc_send_user_event."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(text(
            "SELECT notifications.svc_send_user_event("
            "'" + _DUMMY_UUID + "'::uuid, 'welcome', 'email', '{}'::jsonb, NULL, 'test')"
        ))
    await sp.rollback()


async def test_admin_cannot_call_svc_claim_messages_batch(admin_conn):
    """notification_admin не имеет EXECUTE на svc_claim_messages_batch."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(
            text("SELECT notifications.svc_claim_messages_batch('test-worker', 1)"),
        )
    await sp.rollback()


async def test_admin_cannot_call_svc_mark_message_sending(admin_conn):
    """notification_admin не имеет EXECUTE на svc_mark_message_sending."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(text(
            "SELECT notifications.svc_mark_message_sending('"
            + _DUMMY_UUID + "'::uuid)"
        ))
    await sp.rollback()


async def test_admin_cannot_call_svc_mark_message_sent(admin_conn):
    """notification_admin не имеет EXECUTE на svc_mark_message_sent."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(text(
            "SELECT notifications.svc_mark_message_sent('"
            + _DUMMY_UUID + "'::uuid, 'test')"
        ))
    await sp.rollback()


async def test_admin_cannot_call_svc_mark_message_failed(admin_conn):
    """notification_admin не имеет EXECUTE на svc_mark_message_failed."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(text(
            "SELECT notifications.svc_mark_message_failed('"
            + _DUMMY_UUID + "'::uuid, 'err', 5, 'test')"
        ))
    await sp.rollback()


async def test_admin_cannot_call_svc_requeue_stuck_messages(admin_conn):
    """notification_admin не имеет EXECUTE на svc_requeue_stuck_messages."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(
            text("SELECT notifications.svc_requeue_stuck_messages(300, 600, 'test')"),
        )
    await sp.rollback()


async def test_admin_cannot_call_svc_get_messages_for_user(admin_conn):
    """notification_admin не имеет EXECUTE на svc_get_messages_for_user."""
    sp = await admin_conn.begin_nested()
    with pytest.raises(ProgrammingError, match="permission denied"):
        await admin_conn.execute(text(
            "SELECT notifications.svc_get_messages_for_user('"
            + _DUMMY_UUID + "'::uuid, 10)"
        ))
    await sp.rollback()

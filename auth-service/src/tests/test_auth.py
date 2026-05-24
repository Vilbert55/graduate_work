import uuid


def test_register_success(client, random_user):
    """Регистрация нового пользователя возвращает токены."""
    user, access, refresh = random_user
    assert access
    assert refresh


def test_register_duplicate_login(client, random_user):
    """Попытка регистрации с уже существующим логином вызывает 409."""
    user, _, _ = random_user
    resp = client.post(
        f"{client.base_url}/register",
        json={
            "login": user["login"],
            "password": "another",
            "first_name": "",
            "last_name": "",
        },
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["detail"]["code"] == "USER_ALREADY_EXISTS"


def test_login_success(client, random_user):
    """Успешный вход возвращает токены."""
    user, _, _ = random_user
    resp = client.post(
        f"{client.base_url}/login",
        json={"login": user["login"], "password": user["password"]},
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens


def test_login_wrong_password(client, random_user):
    """Неверный пароль вызывает 401."""
    user, _, _ = random_user
    resp = client.post(
        f"{client.base_url}/login",
        json={"login": user["login"], "password": "wrong"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["detail"]["code"] == "CREDENTIALS_ERROR"


def test_refresh_success(client, random_user):
    """Обновление access-токена по refresh-токену."""
    _, _, refresh = random_user
    resp = client.post(
        f"{client.base_url}/refresh",
        json={"refresh_token": refresh},
    )
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert "access_token" in new_tokens
    assert new_tokens["refresh_token"] == refresh  # тот же refresh


def test_refresh_invalid_token(client):
    """Невалидный refresh-токен вызывает 401."""
    resp = client.post(
        f"{client.base_url}/refresh",
        json={"refresh_token": "invalid.token.here"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["detail"]["code"] == "UNAUTHORIZED"


def test_logout_success(client, random_user):
    """Выход с устройства удаляет refresh-токен."""
    user, access, refresh = random_user
    resp = client.post(
        f"{client.base_url}/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out successfully"

    # Попытка использовать тот же refresh должна вернуть ошибку
    refresh_resp = client.post(
        f"{client.base_url}/refresh",
        json={"refresh_token": refresh},
    )
    assert refresh_resp.status_code == 401


def test_logout_twice(client, random_user):
    """Повторный logout с тем же токеном вызывает ошибку (токен уже удалён)."""
    _user, access, refresh = random_user
    # первый logout
    client.post(
        f"{client.base_url}/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    # второй logout
    resp2 = client.post(
        f"{client.base_url}/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp2.status_code == 401  # токен не найден


def test_logout_all(client, random_user):
    """Выход со всех устройств удаляет все refresh-токены пользователя."""
    user, access, refresh = random_user
    resp = client.post(
        f"{client.base_url}/logout-all",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out from all devices"

    # Текущий refresh больше не работает
    refresh_resp = client.post(
        f"{client.base_url}/refresh",
        json={"refresh_token": refresh},
    )
    assert refresh_resp.status_code == 401


def test_login_history(client, random_user):
    """История входов должна содержать последний вход."""
    user, access, _ = random_user
    # делаем несколько входов
    for _ in range(3):
        client.post(
            f"{client.base_url}/login",
            json={"login": user["login"], "password": user["password"]},
        )

    resp = client.get(
        f"{client.base_url}/history?limit=5",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) >= 3
    # проверяем структуру записи
    for entry in history:
        assert "id" in entry
        assert "user_agent" in entry
        assert "ip_address" in entry
        assert "created_at" in entry


def test_change_password_success(client, random_user):
    """Смена пароля с корректным старым паролем."""
    user, access, _ = random_user
    new_password = "newsecret456"
    resp = client.post(
        f"{client.base_url}/change-password",
        json={"old_password": user["password"], "new_password": new_password},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Password changed successfully"

    # Проверяем, что можно войти с новым паролем
    login_resp = client.post(
        f"{client.base_url}/login",
        json={"login": user["login"], "password": new_password},
    )
    assert login_resp.status_code == 200


def test_change_password_wrong_old(client, random_user):
    """Смена пароля с неверным старым паролем вызывает 400."""
    user, access, _ = random_user
    resp = client.post(
        f"{client.base_url}/change-password",
        json={"old_password": "wrong", "new_password": "newpass"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["detail"]["code"] == "CREDENTIALS_ERROR"


def test_change_login_success(client, random_user):
    """Успешная смена логина."""
    user, access, _ = random_user
    new_login = f"newlogin_{uuid.uuid4()}@example.com"
    resp = client.patch(
        f"{client.base_url}/change-login",
        json={"new_login": new_login, "password": user["password"]},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Login changed successfully"

    # Проверяем вход с новым логином
    login_resp = client.post(
        f"{client.base_url}/login",
        json={"login": new_login, "password": user["password"]},
    )
    assert login_resp.status_code == 200


def test_change_login_already_taken(client, random_user, random_user_second):
    """Смена логина на уже существующий вызывает 409."""
    user1, access1, _ = random_user
    user2, _, _ = random_user_second  # второй пользователь
    resp = client.patch(
        f"{client.base_url}/change-login",
        json={"new_login": user2["login"], "password": user1["password"]},
        headers={"Authorization": f"Bearer {access1}"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["detail"]["code"] == "LOGIN_ALREADY_TAKEN"


def test_change_login_wrong_password(client, random_user):
    """Смена логина с неверным паролем вызывает 400."""
    user, access, _ = random_user
    resp = client.patch(
        f"{client.base_url}/change-login",
        json={"new_login": "anything", "password": "wrong"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["detail"]["code"] == "CREDENTIALS_ERROR"

def test_get_own_profile(client, random_user):
    """Пользователь может получить свой профиль."""
    user, access, _ = random_user
    resp = client.get(
        f"{client.base_url}/users/{user['id']}",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user["id"]
    assert data["login"] == user["login"]
    assert "roles" in data


def test_get_other_user_profile_as_superuser(client, superuser_token, random_user):
    """Суперпользователь может получить профиль любого пользователя."""
    other_user, _, _ = random_user
    resp = client.get(
        f"{client.base_url}/users/{other_user['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == other_user["id"]


def test_get_other_user_profile_as_ordinary_user(client, random_user, random_user_second):
    """Обычный пользователь не может получить профиль другого пользователя (403)."""
    _user1, access1, _ = random_user
    user2, _, _ = random_user_second
    resp = client.get(
        f"{client.base_url}/users/{user2['id']}",
        headers={"Authorization": f"Bearer {access1}"},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["detail"]["code"] == "PERMISSION_DENIED"


def test_check_permissions_as_superuser(client, superuser_token, superuser_id):
    """Суперпользователь всегда имеет разрешение."""
    resp = client.get(
        f"{client.base_url}/users/{superuser_id}/permissions",
        params={"resource": "movies:view123"},
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_permission"] is True
    assert data["user_id"] == superuser_id
    assert data["resource"] == "movies:view123"


def test_check_permissions_own_as_ordinary_user_no_role(client, random_user):
    """Обычный пользователь без специальных ролей не имеет разрешения (false)."""
    user, access, _ = random_user
    resp = client.get(
        f"{client.base_url}/users/{user['id']}/permissions",
        params={"resource": "movies:view"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_permission"] is False


def test_check_permissions_other_user_as_ordinary_user_forbidden(client, random_user, random_user_second):
    """Обычный пользователь не может проверить права другого пользователя (403)."""
    _user1, access1, _ = random_user
    user2, _, _ = random_user_second
    resp = client.get(
        f"{client.base_url}/users/{user2['id']}/permissions",
        params={"resource": "movies:view"},
        headers={"Authorization": f"Bearer {access1}"},
    )
    assert resp.status_code == 403
    data = resp.json()
    assert data["detail"]["code"] == "PERMISSION_DENIED"

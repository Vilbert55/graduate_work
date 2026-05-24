import uuid


def test_get_roles_empty(client, superuser_token):
    """Начальный список ролей может быть пуст."""
    resp = client.get(
        f"{client.base_url}/roles",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_role(client, superuser_token):
    """Создание новой роли."""
    role_name = f"role_{uuid.uuid4()}"
    resp = client.post(
        f"{client.base_url}/roles",
        json={"name": role_name, "description": "test description"},
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == role_name
    assert data["description"] == "test description"
    assert "id" in data


def test_create_duplicate_role(client, superuser_token, random_role):
    """Создание роли с уже существующим именем вызывает 409."""
    role = random_role
    resp = client.post(
        f"{client.base_url}/roles",
        json={"name": role["name"], "description": "another"},
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["detail"]["code"] == "CONFLICT"


def test_update_role(client, superuser_token, random_role):
    """Обновление роли (имя и/или описание)."""
    role = random_role
    new_name = f"updated_{uuid.uuid4()}"
    new_desc = "updated description"
    resp = client.put(
        f"{client.base_url}/roles/{role['id']}",
        json={"name": new_name, "description": new_desc},
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == new_name
    assert data["description"] == new_desc


def test_update_role_not_found(client, superuser_token):
    """Обновление несуществующей роли вызывает 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.put(
        f"{client.base_url}/roles/{fake_id}",
        json={"name": "newname"},
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"]["code"] == "ROLE_NOT_FOUND"


def test_delete_role(client, superuser_token, random_role):
    """Удаление роли."""
    role = random_role
    resp = client.delete(
        f"{client.base_url}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 204

    # Проверяем, что роль действительно удалена
    get_resp = client.get(
        f"{client.base_url}/roles",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    roles = get_resp.json()
    assert not any(r["id"] == role["id"] for r in roles)


def test_assign_role_to_user(client, superuser_token, random_user, random_role):
    """Назначение роли пользователю."""
    user, _, _ = random_user
    role = random_role
    resp = client.post(
        f"{client.base_url}/users/{user['id']}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["message"] == "Role assigned"


def test_assign_role_twice_conflict(client, superuser_token, random_user, random_role):
    """Повторное назначение той же роли вызывает 409."""
    user, _, _ = random_user
    role = random_role
    # первый раз
    client.post(
        f"{client.base_url}/users/{user['id']}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    # второй раз
    resp = client.post(
        f"{client.base_url}/users/{user['id']}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["detail"]["code"] == "CONFLICT"


def test_remove_role_from_user(client, superuser_token, random_user, random_role):
    """Удаление роли у пользователя."""
    user, _, _ = random_user
    role = random_role
    # сначала назначим
    client.post(
        f"{client.base_url}/users/{user['id']}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    # удаляем
    resp = client.delete(
        f"{client.base_url}/users/{user['id']}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 204

    # попытка удалить ещё раз — 409
    resp2 = client.delete(
        f"{client.base_url}/users/{user['id']}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp2.status_code == 409


def test_assign_role_to_nonexistent_user(client, superuser_token, random_role):
    """Назначение роли несуществующему пользователю вызывает 404."""
    fake_user_id = "00000000-0000-0000-0000-000000000000"
    role = random_role
    resp = client.post(
        f"{client.base_url}/users/{fake_user_id}/roles/{role['id']}",
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"]["code"] == "USER_NOT_FOUND"

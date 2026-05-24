import uuid

import pytest
import requests


BASE_URL = "http://localhost/auth"


def create_user(client: requests.Session, login_prefix: str = "testuser") -> tuple[dict, str, str]:
    """
    Вспомогательная функция для создания пользователя, логина и получения его данных.
    Возвращает кортеж: (user_data, access_token, refresh_token)
    """
    login = f"{login_prefix}_{uuid.uuid4()}@example.com"
    password = "secret123"

    # Регистрация
    reg_resp = client.post(
        f"{BASE_URL}/register",
        json={
            "login": login,
            "password": password,
            "first_name": "Test",
            "last_name": "User",
        },
    )
    assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.text}"

    # Логин
    login_resp = client.post(
        f"{BASE_URL}/login",
        json={"login": login, "password": password},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    tokens = login_resp.json()
    access = tokens["access_token"]

    # Получение профиля (нужен ID)
    profile_resp = client.get(
        f"{BASE_URL}/users/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert profile_resp.status_code == 200, f"Fetch profile failed: {profile_resp.text}"
    profile = profile_resp.json()
    user_id = profile["id"]

    user_data = {"id": user_id, "login": login, "password": password}
    return user_data, access, tokens["refresh_token"]


@pytest.fixture(scope="session")
def client() -> requests.Session:
    """HTTP-клиент с базовым URL."""
    session = requests.Session()
    session.base_url = BASE_URL
    return session


@pytest.fixture(scope="session")
def superuser_token(client) -> str:
    """Токен доступа суперпользователя (admin)."""
    resp = client.post(
        f"{BASE_URL}/login",
        json={"login": "admin", "password": "strong-password"},
    )
    assert resp.status_code == 200, "Superuser login failed"
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def superuser_id(client) -> str:
    """id суперпользователя (admin)."""
    login_resp = client.post(
        f"{BASE_URL}/login",
        json={"login": "admin", "password": "strong-password"},
    )
    assert login_resp.status_code == 200, "Superuser login failed"
    tokens = login_resp.json()
    access = tokens["access_token"]
    profile_resp = client.get(
        f"{BASE_URL}/users/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert profile_resp.status_code == 200, f"Fetch profile failed: {profile_resp.text}"
    profile = profile_resp.json()
    return profile["id"]


@pytest.fixture
def random_user(client) -> tuple[dict, str, str]:
    """Создаёт и возвращает нового пользователя."""
    return create_user(client, "testuser")


@pytest.fixture
def random_user_second(client) -> tuple[dict, str, str]:
    """Создаёт второго независимого пользователя."""
    return create_user(client, "seconduser")


@pytest.fixture
def random_role(client, superuser_token) -> dict:
    """Создаёт роль с уникальным именем и возвращает её данные."""
    role_name = f"role_{uuid.uuid4()}"
    resp = client.post(
        f"{BASE_URL}/roles",
        json={"name": role_name, "description": "test role"},
        headers={"Authorization": f"Bearer {superuser_token}"},
    )
    assert resp.status_code == 201, f"Role creation failed: {resp.text}"
    return resp.json()

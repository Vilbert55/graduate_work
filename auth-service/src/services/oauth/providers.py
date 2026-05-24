from abc import ABC, abstractmethod
from urllib.parse import urlencode

import httpx

from src.core.config import settings


class OAuthProvider(ABC):
    """Базовый класс для OAuth2 провайдеров."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        """Возвращает URL для редиректа пользователя."""

    @abstractmethod
    async def handle_callback(self, code: str) -> dict:
        """
        Обменивает код на токен, получает информацию о пользователе
        и возвращает унифицированный словарь с полями:
        provider_user_id, email, first_name, last_name, login.
        """


class YandexProvider(OAuthProvider):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.client_id = settings.yandex_client_id
        self.client_secret = settings.yandex_client_secret

    def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "scope": "login:email login:info",
            "state": state,
            "redirect_uri": redirect_uri,
        }
        return f"https://oauth.yandex.ru/authorize?{urlencode(params)}"

    async def _exchange_code(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth.yandex.ru/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        resp.raise_for_status()
        return resp.json()

    async def _get_user_info(self, access_token: str) -> dict:  # noqa: PLR6301
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://login.yandex.ru/info?format=json",
                headers={"Authorization": f"OAuth {access_token}"},
            )
        resp.raise_for_status()
        return resp.json()

    async def handle_callback(self, code: str) -> dict:
        token_data = await self._exchange_code(code)
        access_token = token_data["access_token"]
        user_info = await self._get_user_info(access_token)

        return {
            "provider_user_id": str(user_info["id"]),
            "email": user_info.get("default_email"),
            "first_name": user_info.get("first_name"),
            "last_name": user_info.get("last_name"),
            "login": user_info.get("login"),
        }


_providers = {
    "yandex": YandexProvider,
}


def get_provider(provider_name: str) -> OAuthProvider:
    provider_class = _providers.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unsupported OAuth provider: {provider_name}")
    return provider_class(provider_name)

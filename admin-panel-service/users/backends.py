import http
import json
from enum import StrEnum, auto

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend


User = get_user_model()


class Roles(StrEnum):
    ADMIN = auto()
    SUBSCRIBER = auto()


class CustomBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None):
        url = settings.AUTH_API_LOGIN_URL
        payload = {'login': username, 'password': password}
        response = requests.post(url, data=json.dumps(payload))
        if response.status_code != http.HTTPStatus.OK:
            return None

        data = response.json()

        try:
            user, created = User.objects.get_or_create(
                #id=data['refresh_token']
            )
            user.email = data.get('email', f'{username}@1.ru')
            user.first_name = data.get('first_name', 'refresh_token')
            user.last_name = data.get('last_name', 'refresh_token')
            user.is_admin = True
            #user.is_admin = data.get('role') == Roles.ADMIN
            user.is_active = data.get('is_active', True)
            user.save()
        except Exception as e:
            print(e)
            return None

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

https://github.com/Vilbert55/Auth_sprint_1
# Сервис авторизации (auth‑service)

Микросервис на FastAPI, отвечающий за аутентификацию пользователей, выдачу JWT‑токенов и управление ролями (RBAC).  
Работает в связке с PostgreSQL (схема `auth`) и Redis (хранение хешей refresh‑токенов, кэширование).

## Возможности

- Регистрация пользователя
- Вход (логин/пароль) -> выдача пары `access` / `refresh` токенов
- Обновление access‑токена по refresh‑токену
- Выход из текущего устройства или из всех устройств
- Изменение логина и пароля
- Просмотр истории входов
- CRUD для ролей (только суперпользователь)
- Назначение и отзыв ролей у пользователей
- Проверка прав доступа к ресурсам

## Технологии

- **FastAPI** + Uvicorn
- **PostgreSQL 16** (SQLAlchemy + asyncpg)
- **Redis 7** (хранение хешей refresh‑токенов и кэш пользователей)
- **JWT** (async‑fastapi‑jwt‑auth)
- **Alembic** (миграции)
- **Pytest** (тесты)
- **Docker**

## Быстрый запуск

Сервис запускается в общем docker‑compose из корня проекта.  
После выполнения `docker compose up -d --build` сервис будет доступен по адресу `http://localhost/auth/`.

Документация OpenAPI (Swagger): `http://localhost/auth/docs`.

## Переменные окружения

### Общие настройки (без префикса)

| Переменная           | Описание                              | По умолчанию    |
|----------------------|---------------------------------------|-----------------|
| `POSTGRES_USER`      | Пользователь PostgreSQL               | postgres        |
| `POSTGRES_PASSWORD`  | Пароль PostgreSQL                     | **обязательно** |
| `POSTGRES_DB`        | Имя БД                                | movies          |
| `SQL_HOST`           | Хост PostgreSQL                       | localhost       |
| `DB_PORT`            | Порт PostgreSQL                       | 5438            |
| `REDIS_HOST`         | Хост Redis                            | 127.0.0.1       |
| `REDIS_PORT`         | Порт Redis                            | 6379            |
| `LOG_LEVEL`          | Уровень логирования                   | INFO            |

### Специфичные для сервиса авторизации (префикс AUTH_)

| Переменная                          | Описание                                       | По умолчанию      |
|-------------------------------------|------------------------------------------------|-------------------|
| `AUTH_JWT_SECRET_KEY`               | Секретный ключ JWT                             | **обязательно**   |
| `AUTH_JWT_ALGORITHM`                | Алгоритм подписи                               | HS256             |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES`  | Время жизни access-токена (мин)                | 15                |
| `AUTH_REFRESH_TOKEN_EXPIRE_DAYS`    | Время жизни refresh-токена (дней)              | 30                |
| `AUTH_SUPERUSER_LOGIN`              | Логин суперпользователя (создаётся при старте) | -                 |
| `AUTH_SUPERUSER_PASSWORD`           | Пароль суперпользователя                       | -                 |
| `AUTH_SERVER_PORT`                  | Порт сервера                                   | 8002              |
| `AUTH_SERVER_RELOAD`                | Авто‑перезагрузка (dev)                        | False             |
| `AUTH_DEBUG`                        | Режим отладки (SQL логи)                       | False             |
| `AUTH_LOGIN_RATE_LIMIT_REQUESTS`    | Макс. число попыток входа за период            | **обязательно**   |
| `AUTH_LOGIN_RATE_LIMIT_PERIOD`      | Период (сек) для лимита входа                  | **обязательно**   |
| `AUTH_REGISTER_RATE_LIMIT_REQUESTS` | Макс. число регистраций за период              | **обязательно**   |
| `AUTH_REGISTER_RATE_LIMIT_PERIOD`   | Период (сек) для лимита регистраций            | **обязательно**   |
| `AUTH_YANDEX_CLIENT_ID`             | Идентификатор приложения Яндекс OAuth          | **обязательно**   |
| `AUTH_YANDEX_CLIENT_SECRET`         | Секретный ключ приложения Яндекс OAuth         | **обязательно**   |


## Эндпоинты

| Метод | Путь                                       | Описание                              |
|-------|--------------------------------------------|---------------------------------------|
| POST  | `/auth/register`                           | Регистрация нового пользователя       |
| POST  | `/auth/login`                              | Вход (получение токенов)              |
| POST  | `/auth/refresh`                            | Обновление access‑токена              |
| POST  | `/auth/logout`                             | Выход с текущего устройства           |
| POST  | `/auth/logout-all`                         | Выход со всех устройств               |
| GET   | `/auth/history`                            | История входов                        |
| POST  | `/auth/change-password`                    | Смена пароля                          |
| PATCH | `/auth/change-login`                       | Изменение логина                      |
| GET   | `/auth/oauth/login/{provider}`             | Инициализация OAuth (редирект)        |
| GET   | `/auth/oauth/link/{provider}`              | Привязка соцсети к аккаунту           |
| GET   | `/auth/oauth/callback/register/{provider}` | Колбэк для входа/регистрации          |
| GET   | `/auth/oauth/callback/login/{provider}`    | Колбэк для привязки                   |
| GET   | `/auth/roles`                              | Список ролей (superuser)              |
| POST  | `/auth/roles`                              | Создание роли (superuser)             |
| PUT   | `/auth/roles/{role_id}`                    | Обновление роли (superuser)           |
| DELETE| `/auth/roles/{role_id}`                    | Удаление роли (superuser)             |
| POST  | `/auth/users/{user_id}/roles/{role_id}`    | Назначить роль (superuser)            |
| DELETE| `/auth/users/{user_id}/roles/{role_id}`    | Отозвать роль (superuser)             |
| GET   | `/auth/users/me`                           | Профиль текущего пользователя         |
| GET   | `/auth/users/{user_id}`                    | Профиль пользователя (superuser/self) |
| GET   | `/auth/users/{user_id}/permissions`        | Проверка прав на ресурс               |


## Управление суперпользователем

При старте контейнера, если заданы переменные `SUPERUSER_LOGIN` и `SUPERUSER_PASSWORD`, суперпользователь создаётся автоматически.  
Также доступна консольная команда внутри контейнера:

```bash
docker exec -it movies-auth-service python cli.py create-superuser <login> <пароль>
```

## Тестирование

Для запуска тестов требуется работающая инфраструктура (PostgreSQL, Redis), поднятая через docker-compose из корня проекта.

### Локальный запуск тестов (вне контейнера)

1. Убедитесь, что установлен **Python 3.12.13** и **poetry**.
2. Перейдите в директорию `auth-service` и установите зависимости, включая группу `test`:
   ```bash
   cd auth-service
   poetry install --with test
   ```
3. Запустите тесты:
   ```bash
   poetry run pytest src/tests -v
   ```
   (или, если активировано виртуальное окружение, просто `pytest src/tests -v`)

### Запуск тестов из корня проекта (после поднятия контейнеров и установки зависимостей)

```bash
docker compose up -d --build
pytest auth-service/src/tests -v
```

## Структура сервиса

```
auth-service/
├── src/
│   ├── api/               # Роутеры FastAPI (auth, users, roles)
│   ├── core/              # Конфигурация, security, логгер, исключения
│   ├── db/                 # Подключение к PostgreSQL и Redis
│   ├── models/             # SQLAlchemy‑модели (User, Role, ...)
│   ├── schemas/            # Pydantic‑схемы запросов/ответов
│   ├── services/           # Бизнес‑логика (AuthService, UserService, RoleService)
│   └── utils/              # Зависимости, вспомогательные функции
├── alembic/                 # Миграции БД
├── tests/                   # Тесты (pytest)
├── cli.py                    # CLI для создания суперпользователя
├── Dockerfile
├── docker-entrypoint.sh
└── pyproject.toml
```

"""Superset config: метаданные хранятся в общей movies-db (схема superset.*).

Безопасных умолчаний здесь нет — SECRET_KEY, логин/пароль admin берутся
из переменных окружения, заданных в .env.
"""
import os


# Обязательное: должен быть стабильным между перезапусками, иначе развалятся сессии.
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Метаданные Superset — в общей Postgres-инстансе проекта (отдельная база `superset`,
# создаётся init-контейнером superset-db-init по аналогии с glitchtip).
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@movies-db:5432/superset"
)

# Включаем нужные фичи. EMBEDDED_SUPERSET позволит при желании
# встраивать дашборды в admin-panel.
FEATURE_FLAGS = {
    "DASHBOARD_RBAC": True,
    "DASHBOARD_NATIVE_FILTERS": True,
    "ALERT_REPORTS": False,
    "EMBEDDED_SUPERSET": True,
}

# Worker-сервер встроенный (Gunicorn) — для дипломного демо одного процесса достаточно.
ROW_LIMIT = 5000
SUPERSET_WEBSERVER_TIMEOUT = 60

# Маппинг "пустой пользователь" → роль Public пуст по умолчанию (без анонимного доступа).
PUBLIC_ROLE_LIKE = None

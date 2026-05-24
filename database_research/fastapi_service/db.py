import os

from psycopg2 import pool
from pymongo import MongoClient


DB_ENGINE = os.getenv("DB_ENGINE", "mongo")  # "mongo" или "postgres"
DB_NAME = os.getenv("DB_NAME", "ugc")

# MongoDB-клиент (создаётся один раз)
mongo_client = None
# PostgreSQL пул соединений
pg_pool = None


def init_mongo():
    global mongo_client  # noqa: PLW0603
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/?replicaSet=rs0&maxPoolSize=10")
    mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)


def init_postgres():
    global pg_pool  # noqa: PLW0603
    pg_host = os.getenv("DB_HOST", "localhost")
    pg_port = os.getenv("DB_PORT", "5432")
    pg_user = os.getenv("DB_USER", "ugc")
    pg_password = os.getenv("DB_PASSWORD", "ugc")
    pg_pool = pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=10,
        host=pg_host,
        port=pg_port,
        dbname=DB_NAME,
        user=pg_user,
        password=pg_password
    )


def get_mongo_db():
    if mongo_client is None:
        init_mongo()
    return mongo_client[DB_NAME]


def get_pg_connection():
    if pg_pool is None:
        init_postgres()
    return pg_pool.getconn()


def return_pg_connection(conn):
    if pg_pool:
        pg_pool.putconn(conn)


def check_health():
    """Проверяет доступность текущей БД."""
    if DB_ENGINE == "mongo":
        try:
            db = get_mongo_db()
            db.command("ping")
            return True  # noqa: TRY300
        except Exception:  # noqa: BLE001
            return False
    elif DB_ENGINE == "postgres":
        conn = None
        try:
            conn = get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True  # noqa: TRY300
        except Exception:  # noqa: BLE001
            return False
        finally:
            if conn:
                return_pg_connection(conn)
    return False

FROM apache/superset:6.1.0

USER root

# mysqlclient (MySQLdb) собирается из исходников — нужны заголовки и компилятор.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-libmysqlclient-dev build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Драйверы:
#  - starrocks       — SQLAlchemy dialect для StarRocks (соединение через pymysql)
#  - psycopg2-binary — Superset хранит метаданные в Postgres (общая movies-db)
#  - mysqlclient     — даёт модуль MySQLdb; Superset MySQLEngineSpec.get_datatype
#                      (наследуется StarRocksEngineSpec) импортирует MySQLdb.constants
#                      для маппинга кодов типов колонок при fetch результатов.
# ВАЖНО: образ apache/superset 6.x использует venv /app/.venv (без pip внутри),
# пакеты ставятся через uv. Системный pip кладёт в /usr/local, где
# /app/.venv/bin/python их не видит — поэтому ставим uv-ом прямо в venv.
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    starrocks==1.2.2 \
    psycopg2-binary==2.9.10 \
    mysqlclient==2.2.4

COPY superset_config.py /app/pythonpath/superset_config.py
COPY init/superset_init.sh /app/init/superset_init.sh
RUN chmod +x /app/init/superset_init.sh

USER superset

ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py
ENV PYTHONPATH=/app/pythonpath:$PYTHONPATH

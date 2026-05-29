FROM apache/superset:6.1.0

USER root

# Драйверы:
#  - starrocks   — официальный SQLAlchemy dialect для StarRocks (MySQL-протокол)
#  - psycopg2-binary — Superset хранит метаданные в Postgres (общая movies-db)
RUN pip install --no-cache-dir \
    starrocks==1.2.2 \
    psycopg2-binary==2.9.10

COPY superset_config.py /app/pythonpath/superset_config.py
COPY init/superset_init.sh /app/init/superset_init.sh
RUN chmod +x /app/init/superset_init.sh

USER superset

ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py
ENV PYTHONPATH=/app/pythonpath:$PYTHONPATH

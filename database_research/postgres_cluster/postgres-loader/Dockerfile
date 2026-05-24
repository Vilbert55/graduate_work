FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY postgres_cluster/postgres-loader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py utils.py ./
COPY postgres_cluster/postgres-loader/generate_and_load.py .

CMD ["python", "generate_and_load.py"]

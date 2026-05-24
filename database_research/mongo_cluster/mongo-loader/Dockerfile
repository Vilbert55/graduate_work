FROM python:3.12-slim

WORKDIR /app

COPY mongo_cluster/mongo-loader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py utils.py ./
COPY mongo_cluster/mongo-loader/generate_and_load.py .

CMD ["python", "generate_and_load.py"]
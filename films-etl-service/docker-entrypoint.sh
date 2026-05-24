#!/bin/bash

# Ожидаем доступности Elasticsearch
until curl -s $ELASTICSEARCH_SCHEMA$ELASTICSEARCH_HOST:$ELASTICSEARCH_PORT > /dev/null; do
  echo 'Waiting for Elasticsearch...'
  sleep 5
done

# Однократная проверка и создание индекса
if ! curl -s -f $ELASTICSEARCH_SCHEMA$ELASTICSEARCH_HOST:$ELASTICSEARCH_PORT/movies > /dev/null; then
  echo "Creating index movies..."
  if [ -f /tmp/es_schema_movies.json ]; then
    curl -X PUT "$ELASTICSEARCH_SCHEMA$ELASTICSEARCH_HOST:$ELASTICSEARCH_PORT/movies" -H 'Content-Type: application/json' --data-binary @/tmp/es_schema_movies.json
    echo "Index movies created."
  else
    echo "Error: es_schema_movies.json not found at /tmp/es_schema_movies.json"
    exit 1
  fi
else
  echo "Index movies already exists."
fi

# Запускаем основной процесс
exec "$@"
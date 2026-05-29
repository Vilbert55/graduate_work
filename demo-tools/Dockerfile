FROM python:3.12.13-slim

WORKDIR /opt/demo-tools

RUN apt-get update && apt-get install -y \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.4.0
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml ./
RUN poetry install --no-interaction --no-ansi --without dev --no-root

COPY . .

# Точка входа = typer-приложение; команда передаётся docker compose run ... <cmd>
ENTRYPOINT ["python", "-m", "src"]
CMD ["--help"]

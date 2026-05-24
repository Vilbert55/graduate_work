#!/bin/bash
#! -path "*/tests/*" \

> content.txt

find ./community-content-service/src -type f \
    ! -name "poetry.lock" \
    ! -name "cr.sh" \
    ! -name "content.txt" \
    ! -name "database_dump.sql" \
    ! -name "ruff.toml" \
    ! -name ".gitignore" \
    ! -name ".env.template" \
    ! -path "*/.vscode/*" \
    ! -path "*/.venv/*" \
    ! -path "*/.pytest_cache/*" \
    ! -path "*/tests/*" \
    ! -path "*/admin-panel-service/*" \
    ! -path "*/auth-service/*" \
    ! -path "*/films-etl-service/*" \
    ! -path "*/migrations/*" \
    ! -path "*/.git/*" \
    ! -path "*/.claude/*" \
    ! -path "*/node_modules/*" \
    ! -path "*/__pycache__/*" \
    ! -name "*.pyc" \
    -print0 | while IFS= read -r -d $'\0' f; do
    echo ">>>>>$(realpath "$f"):" >> content.txt
    cat "$f" >> content.txt
    echo >> content.txt
done
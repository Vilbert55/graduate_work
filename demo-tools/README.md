# demo-tools

CLI-утилиты для подготовки демо-сценариев дипломного `alerting-service`.
Не запускаются автоматически — поднимаются по требованию через профиль `demo`:

```bash
# Создать 50 демо-пользователей (идемпотентно: предыдущих с is_demo=TRUE удалит).
docker compose --profile demo run --rm movies-demo-tools \
    seed-users --count 50

# Сценарий «возврат угасшего» — серия просмотров 30..8 дней назад, потом тишина.
docker compose --profile demo run --rm movies-demo-tools \
    trigger-events --scenario winback --count 30

# Сценарий «тренд в сегменте» — всплеск одного фильма от пользователей сегмента.
docker compose --profile demo run --rm movies-demo-tools \
    trigger-events --scenario segment_trend --segment female_25-34_RU

# Сценарий «выходной всплеск» — просмотры только в субботу-воскресенье.
docker compose --profile demo run --rm movies-demo-tools \
    trigger-events --scenario weekend_burst --count 40
```

## Идемпотентность

`seed-users` — идемпотентен. Маркер демо-пользователя — `auth.users.is_demo = TRUE`,
повторный запуск удалит всех таких и создаст заново. На реальных пользователей
команда не повлияет.

## Структура

```
demo-tools/
├── pyproject.toml
├── Dockerfile
└── src/
    ├── __init__.py
    ├── __main__.py         # typer-app: точка входа
    ├── config.py
    ├── seed_users.py       # подкоманда seed-users
    └── trigger_events.py   # подкоманда trigger-events
```

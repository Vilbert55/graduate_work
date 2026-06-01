"""Демо-утилиты дипломного проекта.

Под-команды:
  seed-users      — создать N демо-пользователей в auth.users (идемпотентно).
  trigger-events  — лить события в Kafka от демо-пользователей по сценарию.
"""
import typer

from src.seed_users import seed_users_cmd
from src.trigger_events import trigger_events_cmd


app = typer.Typer(help=__doc__, no_args_is_help=True)
app.command(name="seed-users")(seed_users_cmd)
app.command(name="trigger-events")(trigger_events_cmd)


if __name__ == "__main__":
    app()

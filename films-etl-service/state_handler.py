import json
from pathlib import Path

from models import StateData


class JsonFileStorage:
    """Хранилище состояния в JSON файле."""

    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def save_state(self, state_data: StateData) -> None:
        """Сохранить состояние."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            json.dumps(state_data.to_storage(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def load_state(self) -> StateData:
        """Загрузить состояние."""
        if self.file_path.exists():
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            return StateData.from_storage(data)
        return StateData()


class State:
    """Менеджер состояния ETL процесса."""

    def __init__(self, storage: JsonFileStorage) -> None:
        self.storage = storage
        self._state_data = self.storage.load_state()

    def set_state(self, **kwargs) -> None:
        """Установить состояние."""
        for key, value in kwargs.items():
            setattr(self._state_data, key, value)
        self.storage.save_state(self._state_data)

    def get_state(self) -> StateData:
        """Получить текущее состояние."""
        return self._state_data

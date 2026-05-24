import random
import uuid
from datetime import UTC, datetime, timedelta


def generate_ids(count: int) -> list[str]:
    """Генерирует список уникальных идентификаторов."""
    return [str(uuid.uuid4()) for _ in range(count)]

def random_text(min_len: int, max_len: int) -> str:
    """Генерирует случайный текст-отзыв."""
    length = random.randint(min_len, max_len)
    words = [
        "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit",
        "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore", "et", "dolore",
        "magna", "aliqua", "film", "movie", "great", "boring", "awesome", "plot",
        "actor", "director", "scene", "soundtrack", "cinematography", "ending"
    ]
    return " ".join(random.choices(words, k=length // 4))

def random_timestamp(days_back: int) -> str:
    """Генерирует случайную дату в формате ISO 8601 (Z-окончание)."""
    now = datetime.now(UTC)
    delta = timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )
    return (now - delta).strftime('%Y-%m-%dT%H:%M:%SZ')

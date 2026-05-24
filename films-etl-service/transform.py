from models import FilmData


def transform_film_data(film_data: list[FilmData]) -> list[dict]:
    """Преобразовать данные о фильмах для Elasticsearch."""
    return [film.model_dump() for film in film_data]

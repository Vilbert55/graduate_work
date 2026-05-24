from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

import backoff
import psycopg2
from config import config
from logger import logger
from models import FilmData, FilmWorkChange, GenreBase, PersonRole
from psycopg2.extras import DictCursor


class PostgresExtractor:
    """Извлечение данных из PostgreSQL."""

    def __init__(self, batch_size: int = config.etl.batch_size) -> None:
        self.dsn = config.postgres.model_dump()
        self.batch_size = batch_size

    @backoff.on_exception(
        backoff.expo,
        psycopg2.OperationalError,
        max_tries=10,
        logger=logger,
    )
    def _get_connection(self) -> psycopg2.extensions.connection:
        """Получить соединение с PostgreSQL."""
        return psycopg2.connect(**self.dsn, cursor_factory=DictCursor)

    @contextmanager
    def _get_cursor(self) -> Generator[DictCursor, None, None]:
        """Контекстный менеджер для курсора."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                yield cursor
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def extract_changed_film_ids(
        self,
        extract_dttm_current: datetime,
        extract_dttm_last: datetime,
        offset: int = 0,
    ) -> tuple[list[FilmWorkChange], bool]:
        """Извлекает id измененных фильмов."""
        with self._get_cursor() as cursor:
            query = """
                SELECT id, title, changed
                FROM content.film_work_changes
                WHERE changed <= %s AND changed > %s
                ORDER BY changed, id
                LIMIT %s OFFSET %s
            """

            cursor.execute(query, (
                extract_dttm_current,
                extract_dttm_last,
                self.batch_size,
                offset,
            ))

            changes = [FilmWorkChange(**row) for row in cursor.fetchall()]
            has_more = len(changes) == self.batch_size

            return changes, has_more

    def extract_film_data(self, film_ids: list[str]) -> list[FilmData]:
        """Извлекает полные данные о фильмах."""
        if not film_ids:
            return []

        with self._get_cursor() as cursor:
            # базовые данные фильмов
            film_query = """
                SELECT
                    fw.id,
                    fw.title,
                    fw.description,
                    fw.rating,
                    fw.type,
                    fw.creation_date
                FROM content.film_work fw
                WHERE fw.id = ANY(%s::uuid[])
            """
            cursor.execute(film_query, (film_ids,))
            films = {row['id']: row for row in cursor.fetchall()}

            # жанры
            genre_query = """
                SELECT
                    gfw.film_work_id,
                    g.id,
                    g.name
                FROM content.genre_film_work gfw
                JOIN content.genre g ON gfw.genre_id = g.id
                WHERE gfw.film_work_id = ANY(%s::uuid[])
            """
            cursor.execute(genre_query, (film_ids,))
            film_genres = defaultdict(list)
            for row in cursor.fetchall():
                genre = GenreBase(id=row["id"], name=row["name"])
                film_genres[row['film_work_id']].append(genre)

            # персоны
            person_query = """
                SELECT
                    pfw.film_work_id,
                    pfw.role,
                    p.id,
                    p.full_name
                FROM content.person_film_work pfw
                JOIN content.person p ON pfw.person_id = p.id
                WHERE pfw.film_work_id = ANY(%s::uuid[])
            """
            cursor.execute(person_query, (film_ids,))

            film_persons = defaultdict(lambda: defaultdict(list))
            for row in cursor.fetchall():
                person_role = PersonRole(id=row["id"], name=row["full_name"])
                match row["role"]:
                    case "director":
                        film_persons[row["film_work_id"]]["directors"].append(person_role)
                    case "actor":
                        film_persons[row["film_work_id"]]["actors"].append(person_role)
                    case "writer":
                        film_persons[row["film_work_id"]]["writers"].append(person_role)

            # Формируем результат
            result = []
            for film in films.values():
                film_id = film["id"]

                film_data = FilmData(
                    id=film_id,
                    title=film["title"],
                    description=film["description"],
                    imdb_rating=film["rating"],
                    genres=film_genres[film_id],
                    directors=film_persons[film_id]["directors"],
                    actors=film_persons[film_id]["actors"],
                    writers=film_persons[film_id]["writers"],
                )

                # Добавляем вычисляемые поля
                film_data.directors_names = [p.name for p in film_data.directors]
                film_data.actors_names = [p.name for p in film_data.actors]
                film_data.writers_names = [p.name for p in film_data.writers]

                result.append(film_data)

            return result

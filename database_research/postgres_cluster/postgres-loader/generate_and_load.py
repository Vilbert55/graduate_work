import io
import os
import random
import time
from datetime import datetime
from multiprocessing import Process

import config
import psycopg2
from utils import generate_ids, random_text, random_timestamp


DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "ugc")
DB_USER = os.getenv("DB_USER", "ugc")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ugc")

ROWS_PER_COPY = 500_000

# Индексы, которые будут созданы ПОСЛЕ загрузки, как в MongoDB
POST_INDEXES = {
    "film_scores": [
        "CREATE INDEX IF NOT EXISTS idx_film_scores_user_id ON film_scores (user_id);",
        "CREATE INDEX IF NOT EXISTS idx_film_scores_movie_id ON film_scores (movie_id);",
        "CREATE INDEX IF NOT EXISTS idx_film_scores_movie_score ON film_scores (movie_id, score);"
    ],
    "reviews": [
        "CREATE INDEX IF NOT EXISTS idx_reviews_movie_created ON reviews (movie_id, created_at DESC);"
    ],
    "bookmarks": [
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_user_id ON bookmarks (user_id);"
    ],
    "review_likes": [
        "CREATE INDEX IF NOT EXISTS idx_review_likes_review_id ON review_likes (review_id);"
    ]
}


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def wait_for_pg(timeout=120):
    print("Waiting for PostgreSQL...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD
            )
            conn.close()
            print("PostgreSQL is ready.")
            return
        except psycopg2.OperationalError:
            time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready in time.")


def copy_from_csv(conn, table, columns, csv_buf):
    """Загружает данные из StringIO через COPY."""
    with conn.cursor() as cur:
        cur.copy_expert(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH CSV",
            csv_buf
        )
    conn.commit()


def insert_movies(conn, movie_ids):
    print(f"Inserting {len(movie_ids)} movies...")
    buf = io.StringIO()
    for mid in movie_ids:
        buf.write(f"{mid}\n")
    buf.seek(0)
    copy_from_csv(conn, "movies", ["movie_id"], buf)
    print("  Done.")


def insert_users(conn, user_ids):
    print(f"Inserting {len(user_ids)} users...")
    buf = io.StringIO()
    for uid in user_ids:
        buf.write(f"{uid}\n")
    buf.seek(0)
    copy_from_csv(conn, "users", ["user_id"], buf)
    print("  Done.")


def insert_reviews(conn, review_ids, user_ids, movie_ids):
    print(f"Generating and inserting {len(review_ids)} reviews...")
    buf = io.StringIO()
    idx = 0
    for review_id in review_ids:
        user_id = random.choice(user_ids)
        movie_id = random.choice(movie_ids)
        text = random_text(config.REVIEW_TEXT_MIN_LENGTH,
                           config.REVIEW_TEXT_MAX_LENGTH)
        ts = random_timestamp(config.DAYS_BACK_FOR_REVIEWS)
        created_at = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        escaped_text = text.replace('"', '""')
        buf.write(f'{review_id},{user_id},{movie_id},"{escaped_text}",{created_at}\n')
        idx += 1
        if idx % ROWS_PER_COPY == 0:
            buf.seek(0)
            copy_from_csv(conn, "reviews",
                          ["review_id", "user_id", "movie_id", "text", "created_at"],
                          buf)
            buf = io.StringIO()
    if idx % ROWS_PER_COPY != 0:
        buf.seek(0)
        copy_from_csv(conn, "reviews",
                      ["review_id", "user_id", "movie_id", "text", "created_at"],
                      buf)
    print(f"  {len(review_ids)} reviews inserted.")


def _generate_film_scores(movie_ids, user_ids, total):
    for _ in range(total):
        yield f"{random.choice(user_ids)},{random.choice(movie_ids)},{random.randint(1, 10)}\n"


def _generate_bookmarks(movie_ids, user_ids, total):
    for _ in range(total):
        yield f"{random.choice(user_ids)},{random.choice(movie_ids)}\n"


def _generate_review_likes(user_ids, review_ids, total):
    for _ in range(total):
        yield f"{random.choice(user_ids)},{random.choice(review_ids)},{random.choice([-1, 1])}\n"


def _load_table_worker(table, columns, total, movie_ids, user_ids, review_ids=None):
    """Загружает одну таблицу, создавая генератор внутри."""
    if table == "film_scores":
        generator = _generate_film_scores(movie_ids, user_ids, total)
    elif table == "bookmarks":
        generator = _generate_bookmarks(movie_ids, user_ids, total)
    else:  # review_likes
        generator = _generate_review_likes(user_ids, review_ids, total)

    conn = get_connection()
    buf = io.StringIO()
    count = 0
    for line in generator:
        buf.write(line)
        count += 1
        if count % ROWS_PER_COPY == 0:
            buf.seek(0)
            copy_from_csv(conn, table, columns, buf)
            buf = io.StringIO()
    if count % ROWS_PER_COPY != 0:
        buf.seek(0)
        copy_from_csv(conn, table, columns, buf)
    conn.close()
    print(f"  {table}: {total} rows loaded.")


def add_primary_keys_and_create_indexes():
    """Добавляет PK и индексы после загрузки данных."""
    print("Adding constraints...")
    conn = get_connection()
    conn.autocommit = True
    with conn.cursor() as cur:
        # Primary keys для справочных таблиц и reviews
        cur.execute("ALTER TABLE movies ADD PRIMARY KEY (movie_id);")
        cur.execute("ALTER TABLE users ADD PRIMARY KEY (user_id);")
        cur.execute("ALTER TABLE reviews ADD PRIMARY KEY (review_id);")

        for table, statements in POST_INDEXES.items():
            for stmt in statements:
                cur.execute(stmt)
                print(f"  {stmt}")
    conn.close()
    print("Constraints added.")


def main():
    overall_start = time.time()
    wait_for_pg()

    print("Generating IDs...")
    movie_ids = generate_ids(config.NUM_MOVIES)
    user_ids = generate_ids(config.NUM_USERS)
    review_ids = generate_ids(config.NUM_REVIEWS)

    conn = get_connection()
    try:
        insert_movies(conn, movie_ids)
        insert_users(conn, user_ids)
        insert_reviews(conn, review_ids, user_ids, movie_ids)
    finally:
        conn.close()

    print("Launching parallel load for film_scores, bookmarks, review_likes...")
    p1 = Process(target=_load_table_worker, args=(
        "film_scores",
        ["user_id", "movie_id", "score"],
        config.NUM_FILM_SCORES,
        movie_ids, user_ids,
    ))
    p2 = Process(target=_load_table_worker, args=(
        "bookmarks",
        ["user_id", "movie_id"],
        config.NUM_BOOKMARKS,
        movie_ids, user_ids,
    ))
    p3 = Process(target=_load_table_worker, args=(
        "review_likes",
        ["user_id", "review_id", "value"],
        config.NUM_REVIEW_LIKES,
        movie_ids, user_ids, review_ids,
    ))

    p1.start(); p2.start(); p3.start()
    p1.join();  p2.join();  p3.join()

    # Добавляем индексы
    add_primary_keys_and_create_indexes()

    # Проверка итоговых количеств
    print("\nFinal counts:")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for table in ["movies", "users", "film_scores", "reviews",
                          "bookmarks", "review_likes"]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"  {table}: {count}")
    finally:
        conn.close()

    elapsed = time.time() - overall_start
    print(f"\nTotal time: {elapsed:.2f} seconds")
    print("Generation and loading completed successfully!")


if __name__ == "__main__":
    main()

import random
import time
import traceback
from datetime import datetime
from multiprocessing import Process

import config
from pymongo import MongoClient, WriteConcern
from pymongo.errors import AutoReconnect, PyMongoError
from utils import generate_ids, random_text, random_timestamp


MONGO_URI = "mongodb://mongo1:27017/?replicaSet=rs0&maxPoolSize=10"
DB_NAME = "ugc"

NUM_PROCESSES = 4
BATCH_SIZE = 50_000

PRE_INDEXES = {
    "film_scores": [[("user_id", 1)], [("movie_id", 1)], [("movie_id", 1), ("score", 1)]],
    "reviews": [[("movie_id", 1), ("created_at", -1)]],
    "bookmarks": [[("user_id", 1)]],
    "review_likes": [[("review_id", 1)]],
}

def wait_for_mongo(client_uri: str, timeout: int = 120) -> MongoClient:
    print("Waiting for MongoDB replica set to be ready...")
    client = MongoClient(client_uri, serverSelectionTimeoutMS=30000,
                         connectTimeoutMS=30000, socketTimeoutMS=30000)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client.admin.command("ping")
            status = client.admin.command("replSetGetStatus")
            if any(m["stateStr"] == "PRIMARY" for m in status["members"]):
                print("Replica set is ready with PRIMARY.")
                return client
        except PyMongoError:
            pass
        time.sleep(2)
    raise RuntimeError("MongoDB replica set did not become ready in time.")

def insert_many_retry(collection, batch, max_retries=5):
    """Вставка с повторными попытками при обрыве соединения."""
    for attempt in range(1, max_retries + 1):
        try:
            collection.insert_many(batch, ordered=False)
            return len(batch)
        except AutoReconnect as e:
            if attempt == max_retries:
                raise
            print(f"    Retry {attempt}/{max_retries} after: {e}")
            time.sleep(2 ** attempt)
    return None

def load_movies_and_users(client_uri: str, movie_ids: list[str], user_ids: list[str]):
    """Загружает справочники фильмов и пользователей напрямую."""
    client = MongoClient(client_uri)
    db = client[DB_NAME]
    movies_col = db["movies"].with_options(write_concern=WriteConcern(w=0))
    users_col = db["users"].with_options(write_concern=WriteConcern(w=0))

    print("Inserting movies...")
    insert_many_retry(movies_col, [{"movie_id": mid} for mid in movie_ids])
    print(f"  {len(movie_ids)} movies inserted.")

    print("Inserting users...")
    for i in range(0, len(user_ids), BATCH_SIZE):
        batch = [{"user_id": uid} for uid in user_ids[i:i + BATCH_SIZE]]
        insert_many_retry(users_col, batch)
    print(f"  {len(user_ids)} users inserted.")
    client.close()

def generate_and_insert_worker(
    process_id: int,
    movie_ids: list[str],
    user_ids: list[str],
    review_ids: list[str],
    quota_film_scores: int,
    quota_reviews: int,
    quota_bookmarks: int,
    quota_review_likes: int,
):
    """Генерирует и вставляет порции данных."""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=30000,
                             connectTimeoutMS=30000, socketTimeoutMS=30000)
        db = client[DB_NAME]
        film_scores_col = db["film_scores"].with_options(write_concern=WriteConcern(w=0))
        reviews_col = db["reviews"].with_options(write_concern=WriteConcern(w=0))
        bookmarks_col = db["bookmarks"].with_options(write_concern=WriteConcern(w=0))
        review_likes_col = db["review_likes"].with_options(write_concern=WriteConcern(w=0))

        print(f"Process {process_id}: generating "
              f"{quota_film_scores} film_scores, "
              f"{quota_reviews} reviews, "
              f"{quota_bookmarks} bookmarks, "
              f"{quota_review_likes} review_likes")

        counters = {"film_scores": 0, "reviews": 0, "bookmarks": 0, "review_likes": 0}

        def flush_batch(collection, batch, counter_key):
            if batch:
                inserted = insert_many_retry(collection, batch)
                counters[counter_key] += inserted
                batch.clear()

        film_scores_batch = []
        reviews_batch = []
        bookmarks_batch = []
        review_likes_batch = []

        # Генерация film_scores
        for _ in range(quota_film_scores):
            user_id = random.choice(user_ids)
            movie_id = random.choice(movie_ids)
            score = random.randint(1, 10)
            film_scores_batch.append({"user_id": user_id, "movie_id": movie_id, "score": score})
            if len(film_scores_batch) >= BATCH_SIZE:
                flush_batch(film_scores_col, film_scores_batch, "film_scores")

        # Генерация reviews – каждому процессу переданы его собственные review_id
        for i in range(quota_reviews):
            review_id = review_ids[i]
            user_id = random.choice(user_ids)
            movie_id = random.choice(movie_ids)
            text = random_text(config.REVIEW_TEXT_MIN_LENGTH, config.REVIEW_TEXT_MAX_LENGTH)
            created_at_str = random_timestamp(config.DAYS_BACK_FOR_REVIEWS)
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            reviews_batch.append({
                "review_id": review_id,
                "user_id": user_id,
                "movie_id": movie_id,
                "text": text,
                "created_at": created_at
            })
            if len(reviews_batch) >= BATCH_SIZE:
                flush_batch(reviews_col, reviews_batch, "reviews")

        # Генерация bookmarks
        for _ in range(quota_bookmarks):
            user_id = random.choice(user_ids)
            movie_id = random.choice(movie_ids)
            bookmarks_batch.append({"user_id": user_id, "movie_id": movie_id})
            if len(bookmarks_batch) >= BATCH_SIZE:
                flush_batch(bookmarks_col, bookmarks_batch, "bookmarks")

        # Генерация review_likes – используем случайные review_id из глобального пула
        global_review_ids = review_ids  # здесь только локальный список, но для лайков можно брать любые
        for _ in range(quota_review_likes):
            user_id = random.choice(user_ids)
            review_id = random.choice(global_review_ids)
            value = random.choice([1, -1])
            review_likes_batch.append({"user_id": user_id, "review_id": review_id, "value": value})
            if len(review_likes_batch) >= BATCH_SIZE:
                flush_batch(review_likes_col, review_likes_batch, "review_likes")

        # Вставка остатков
        flush_batch(film_scores_col, film_scores_batch, "film_scores")
        flush_batch(reviews_col, reviews_batch, "reviews")
        flush_batch(bookmarks_col, bookmarks_batch, "bookmarks")
        flush_batch(review_likes_col, review_likes_batch, "review_likes")

        print(f"Process {process_id}: done. Inserted: {counters}")
        client.close()
    except Exception:
        print(f"Process {process_id} failed with error:")
        traceback.print_exc()
        raise

def create_all_indexes(client_uri: str):
    client = MongoClient(
        client_uri,
        serverSelectionTimeoutMS=30000,
        connectTimeoutMS=30000,
        socketTimeoutMS=60000,
    )
    db = client[DB_NAME]
    print("Creating indexes...")
    for coll_name, index_list in PRE_INDEXES.items():
        for index_spec in index_list:
            for attempt in range(1, 6):
                try:
                    db[coll_name].create_index(index_spec)
                    print(f"  Index created on {coll_name}: {index_spec}")
                    break
                except AutoReconnect as e:
                    print(f"  Retry {attempt}/5 after AutoReconnect: {e}")
                    time.sleep(5)
            else:
                raise RuntimeError(f"Failed to create index {index_spec} on {coll_name}")
            time.sleep(2)
    client.close()

def main():
    overall_start = time.time()
    client = wait_for_mongo(MONGO_URI)
    client.close()

    print("Generating movies and users...")
    movie_ids = generate_ids(config.NUM_MOVIES)
    user_ids = generate_ids(config.NUM_USERS)
    load_movies_and_users(MONGO_URI, movie_ids, user_ids)

    print("Generating review IDs...")
    review_ids = generate_ids(config.NUM_REVIEWS)  # общий пул ID рецензий

    # Базовые квоты без остатка
    base_fs = config.NUM_FILM_SCORES // NUM_PROCESSES
    base_rev = config.NUM_REVIEWS // NUM_PROCESSES
    base_bm = config.NUM_BOOKMARKS // NUM_PROCESSES
    base_rl = config.NUM_REVIEW_LIKES // NUM_PROCESSES

    # Остатки, которые добавим к последнему процессу
    rem_fs = config.NUM_FILM_SCORES - base_fs * NUM_PROCESSES
    rem_rev = config.NUM_REVIEWS - base_rev * NUM_PROCESSES
    rem_bm = config.NUM_BOOKMARKS - base_bm * NUM_PROCESSES
    rem_rl = config.NUM_REVIEW_LIKES - base_rl * NUM_PROCESSES

    print(f"Launching {NUM_PROCESSES} processes with base quotas: "
          f"films={base_fs}, reviews={base_rev}, bookmarks={base_bm}, likes={base_rl}")

    processes = []
    # Для reviews нужно заранее нарезать список id для каждого процесса
    review_chunks = []
    start = 0
    for pid in range(NUM_PROCESSES):
        proc_rev_quota = base_rev + (rem_rev if pid == NUM_PROCESSES - 1 else 0)
        end = start + proc_rev_quota
        review_chunks.append(review_ids[start:end])
        start = end

    for pid in range(NUM_PROCESSES):
        proc_review_ids = review_chunks[pid]
        proc_fs = base_fs + (rem_fs if pid == NUM_PROCESSES - 1 else 0)
        proc_rev = len(proc_review_ids)
        proc_bm = base_bm + (rem_bm if pid == NUM_PROCESSES - 1 else 0)
        proc_rl = base_rl + (rem_rl if pid == NUM_PROCESSES - 1 else 0)

        p = Process(
            target=generate_and_insert_worker,
            args=(pid, movie_ids, user_ids, proc_review_ids,
                  proc_fs, proc_rev, proc_bm, proc_rl)
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    overall_end = time.time()
    elapsed = overall_end - overall_start
    print("All data inserted. Creating indexes...")
    create_all_indexes(MONGO_URI)

    # Проверка итоговых количеств
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    print("\nFinal document counts:")
    for coll in ["movies", "users", "film_scores", "reviews", "bookmarks", "review_likes"]:
        count = db[coll].count_documents({})
        print(f"  {coll}: {count}")
    client.close()

    print(f"\nTotal time: {elapsed:.2f} seconds")
    print("Generation and loading completed successfully!")


if __name__ == "__main__":
    main()

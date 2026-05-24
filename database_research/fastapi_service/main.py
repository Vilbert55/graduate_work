# fastapi_service/main.py

from db import DB_ENGINE, check_health, get_mongo_db, get_pg_connection, return_pg_connection
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Annotated


app = FastAPI()


class FilmScoreInput(BaseModel):
    user_id: str
    movie_id: str
    score: int = Field(..., ge=0, le=10)


class BookmarkInput(BaseModel):
    user_id: str
    movie_id: str


class LikeItem(BaseModel):
    movie_id: str
    score: int


class MovieStats(BaseModel):
    likes: int
    dislikes: int
    avg_score: float | None = None


class AddResponse(BaseModel):
    status: str = "ok"


class DeleteResponse(BaseModel):
    status: str = "ok"
    deleted_count: int = 0


class RandomIdResponse(BaseModel):
    id: str


@app.get("/health")
def health():
    if check_health():
        return {"status": "ok"}
    raise HTTPException(status_code=503, detail="Database unavailable")


# Random ID helpers
@app.get("/random/user", response_model=RandomIdResponse)
def random_user():
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        docs = db["users"].aggregate([{"$sample": {"size": 1}}]).to_list(1)
        if not docs:
            raise HTTPException(status_code=404, detail="No users found")
        return RandomIdResponse(id=docs[0]["user_id"])
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users ORDER BY RANDOM() LIMIT 1;")
                row = cur.fetchone()
        finally:
            return_pg_connection(conn)
        if not row:
            raise HTTPException(status_code=404, detail="No users found")
        return RandomIdResponse(id=row[0])
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


@app.get("/random/movie", response_model=RandomIdResponse)
def random_movie():
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        docs = db["movies"].aggregate([{"$sample": {"size": 1}}]).to_list(1)
        if not docs:
            raise HTTPException(status_code=404, detail="No movies found")
        return RandomIdResponse(id=docs[0]["movie_id"])
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT movie_id FROM movies ORDER BY RANDOM() LIMIT 1;")
                row = cur.fetchone()
        finally:
            return_pg_connection(conn)
        if not row:
            raise HTTPException(status_code=404, detail="No movies found")
        return RandomIdResponse(id=row[0])
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


@app.get("/random/review", response_model=RandomIdResponse)
def random_review():
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        docs = db["reviews"].aggregate([{"$sample": {"size": 1}}]).to_list(1)
        if not docs:
            raise HTTPException(status_code=404, detail="No reviews found")
        return RandomIdResponse(id=docs[0]["review_id"])
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT review_id FROM reviews ORDER BY RANDOM() LIMIT 1;")
                row = cur.fetchone()
        finally:
            return_pg_connection(conn)
        if not row:
            raise HTTPException(status_code=404, detail="No reviews found")
        return RandomIdResponse(id=row[0])
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


# User likes
@app.get("/user/{user_id}/likes", response_model=list[LikeItem])
def get_user_likes(
    user_id: str,
    min_score: Annotated[int, Query(ge=0, le=10)] = 0,
    max_score: Annotated[int, Query(ge=0, le=10)] = 10,
):
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        cursor = db["film_scores"].find(
            {"user_id": user_id, "score": {"$gte": min_score, "$lte": max_score}},
            {"_id": 0, "movie_id": 1, "score": 1},
        )
        # синхронный курсор, перебираем обычным for
        return [LikeItem(movie_id=doc["movie_id"], score=doc["score"]) for doc in cursor]
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT movie_id, score FROM film_scores "
                    "WHERE user_id = %s AND score BETWEEN %s AND %s;",
                    (user_id, min_score, max_score),
                )
                rows = cur.fetchall()
            return [LikeItem(movie_id=row[0], score=row[1]) for row in rows]
        finally:
            return_pg_connection(conn)
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


# Movie stats
@app.get("/movie/{movie_id}/stats", response_model=MovieStats)
def get_movie_stats(movie_id: str):
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        pipeline = [
            {"$match": {"movie_id": movie_id}},
            {"$group": {
                "_id": None,
                "likes": {"$sum": {"$cond": [{"$eq": ["$score", 10]}, 1, 0]}},
                "dislikes": {"$sum": {"$cond": [{"$eq": ["$score", 0]}, 1, 0]}},
                "avg_score": {"$avg": "$score"},
            }},
        ]
        results = db["film_scores"].aggregate(pipeline).to_list(1)
        if not results:
            return MovieStats(likes=0, dislikes=0, avg_score=None)
        r = results[0]
        return MovieStats(
            likes=r["likes"],
            dislikes=r["dislikes"],
            avg_score=round(r["avg_score"], 2) if r["avg_score"] is not None else None,
        )
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT "
                    "  COALESCE(COUNT(*) FILTER (WHERE score = 10), 0), "
                    "  COALESCE(COUNT(*) FILTER (WHERE score = 0), 0), "
                    "  ROUND(AVG(score)::numeric, 2) "
                    "FROM film_scores WHERE movie_id = %s;",
                    (movie_id,),
                )
                row = cur.fetchone()
        finally:
            return_pg_connection(conn)
        return MovieStats(likes=row[0], dislikes=row[1], avg_score=row[2])
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


# User bookmarks
@app.get("/user/{user_id}/bookmarks", response_model=list[str])
def get_user_bookmarks(user_id: str):
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        cursor = db["bookmarks"].find({"user_id": user_id}, {"_id": 0, "movie_id": 1})
        return [doc["movie_id"] for doc in cursor]
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT movie_id FROM bookmarks WHERE user_id = %s;", (user_id,))
                rows = cur.fetchall()
            return [row[0] for row in rows]
        finally:
            return_pg_connection(conn)
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


# Add film score
@app.post("/film_score", response_model=AddResponse)
def add_film_score(data: FilmScoreInput):
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        db["film_scores"].insert_one({
            "user_id": data.user_id,
            "movie_id": data.movie_id,
            "score": data.score,
        })
        return AddResponse()
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO film_scores (user_id, movie_id, score) VALUES (%s, %s, %s);",
                    (data.user_id, data.movie_id, data.score),
                )
            conn.commit()
        finally:
            return_pg_connection(conn)
        return AddResponse()
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


# Add bookmark
@app.post("/bookmark", response_model=AddResponse)
def add_bookmark(data: BookmarkInput):
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        db["bookmarks"].update_one(
            {"user_id": data.user_id, "movie_id": data.movie_id},
            {"$setOnInsert": {"user_id": data.user_id, "movie_id": data.movie_id}},
            upsert=True,
        )
        return AddResponse()
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO bookmarks (user_id, movie_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    (data.user_id, data.movie_id),
                )
            conn.commit()
        finally:
            return_pg_connection(conn)
        return AddResponse()
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")


# Delete bookmark
@app.delete("/bookmark", response_model=DeleteResponse)
def delete_bookmark(data: BookmarkInput):
    if DB_ENGINE == "mongo":
        db = get_mongo_db()
        result = db["bookmarks"].delete_many({
            "user_id": data.user_id,
            "movie_id": data.movie_id,
        })
        return DeleteResponse(deleted_count=result.deleted_count)
    elif DB_ENGINE == "postgres":
        conn = get_pg_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bookmarks WHERE user_id = %s AND movie_id = %s;",
                    (data.user_id, data.movie_id),
                )
                deleted = cur.rowcount
            conn.commit()
        finally:
            return_pg_connection(conn)
        return DeleteResponse(deleted_count=deleted)
    else:
        raise HTTPException(status_code=500, detail="Unsupported DB_ENGINE")

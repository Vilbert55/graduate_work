-- Таблицы создаются БЕЗ первичных ключей, внешних ключей и индексов
CREATE TABLE movies (
    movie_id UUID NOT NULL
);

CREATE TABLE users (
    user_id UUID NOT NULL
);

CREATE TABLE film_scores (
    user_id UUID NOT NULL,
    movie_id UUID NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10)
);

CREATE TABLE reviews (
    review_id UUID NOT NULL,
    user_id UUID NOT NULL,
    movie_id UUID NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE bookmarks (
    user_id UUID NOT NULL,
    movie_id UUID NOT NULL
);

CREATE TABLE review_likes (
    user_id UUID NOT NULL,
    review_id UUID NOT NULL,
    value SMALLINT NOT NULL CHECK (value IN (-1, 1))
);
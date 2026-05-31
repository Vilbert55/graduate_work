-- Дипломная часть: dim-таблицы и materialized views для alerting-service.
--
-- Этот скрипт применяется ПОСЛЕ starrocks_init/init.sql:
-- зависит от существования ugc_analytics.user_events.
--
-- Подход:
--   1. JDBC Catalog pg_catalog поверх Postgres движка-источника
--      (содержит схемы content и auth).
--   2. Dim-таблицы StarRocks (PRIMARY KEY) — INSERT OVERWRITE из JDBC
--      внутри StarRocks по расписанию SUBMIT TASK. Никакого внешнего
--      Python-ETL — нативный механизм StarRocks (парный к Routine Load).
--   3. Materialized views — async refresh поверх user_events и dim_*.
--   4. Роль alert_reader с правом только на SELECT — её использует
--      alerting-engine.

USE ugc_analytics;

-- ============================================================
-- 1. JDBC Catalog поверх Postgres
-- ============================================================
-- ${POSTGRES_USER} / ${POSTGRES_PASSWORD} подставляются envsubst в entrypoint.
DROP CATALOG IF EXISTS pg_catalog;
CREATE EXTERNAL CATALOG pg_catalog
PROPERTIES (
    "type" = "jdbc",
    "user" = "${POSTGRES_USER}",
    "password" = "${POSTGRES_PASSWORD}",
    "jdbc_uri" = "jdbc:postgresql://movies-db:5432/movies",
    "driver_url" = "https://jdbc.postgresql.org/download/postgresql-42.7.4.jar",
    "driver_class" = "org.postgresql.Driver"
);

-- ============================================================
-- 2. Dim-таблицы (PRIMARY KEY — поддерживают INSERT OVERWRITE)
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_films (
    film_id        VARCHAR(36)   NOT NULL,
    title          VARCHAR(512)  NULL,
    type           VARCHAR(16)   NULL,
    creation_date  DATE          NULL,
    rating         FLOAT         NULL,
    is_new         BOOLEAN       NULL COMMENT 'creation_date > now() - 30d',
    genres         ARRAY<STRING> NULL
)
PRIMARY KEY (film_id)
DISTRIBUTED BY HASH(film_id) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_persistent_index" = "true"
);

CREATE TABLE IF NOT EXISTS dim_users (
    user_id        VARCHAR(36)  NOT NULL,
    gender         VARCHAR(16)  NULL,
    age_group      VARCHAR(16)  NULL,
    country        VARCHAR(2)   NULL,
    segment_code   VARCHAR(64)  NULL COMMENT 'gender_age_country, напр. female_25-34_RU',
    registered_at  DATETIME     NULL,
    is_demo        BOOLEAN      NULL
)
PRIMARY KEY (user_id)
DISTRIBUTED BY HASH(user_id) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_persistent_index" = "true"
);

CREATE TABLE IF NOT EXISTS dim_genres (
    genre_id  VARCHAR(36) NOT NULL,
    name      VARCHAR(255) NULL
)
PRIMARY KEY (genre_id)
DISTRIBUTED BY HASH(genre_id) BUCKETS 2
PROPERTIES (
    "replication_num" = "1",
    "enable_persistent_index" = "true"
);

-- dim_date — задействуем неиспользуемый ранее content.date_dimension
-- из admin-panel-service: позволяет в правилах строить условия "по выходным",
-- "по пятницам", "по праздникам" единообразным JOIN.
CREATE TABLE IF NOT EXISTS dim_date (
    `date`       DATE        NOT NULL,
    year         SMALLINT    NULL,
    quarter      SMALLINT    NULL,
    month        SMALLINT    NULL,
    day          SMALLINT    NULL,
    day_of_week  SMALLINT    NULL,
    week_of_year SMALLINT    NULL,
    is_weekend   BOOLEAN     NULL,
    is_holiday   BOOLEAN     NULL
)
PRIMARY KEY (`date`)
DISTRIBUTED BY HASH(`date`) BUCKETS 4
PROPERTIES (
    "replication_num" = "1",
    "enable_persistent_index" = "true"
);

-- ============================================================
-- 3. Первичная заливка (синхронно, чтобы MV сразу было что считать)
-- ============================================================

INSERT OVERWRITE dim_genres
SELECT
    CAST(id AS VARCHAR(36)) AS genre_id,
    name
FROM pg_catalog.content.genre;

INSERT OVERWRITE dim_films
SELECT
    CAST(f.id AS VARCHAR(36)) AS film_id,
    f.title,
    f.type,
    f.creation_date,
    f.rating,
    f.creation_date IS NOT NULL AND f.creation_date > date_sub(current_date(), INTERVAL 30 DAY) AS is_new,
    (
        SELECT array_agg(g.name)
        FROM pg_catalog.content.genre_film_work gfw
        JOIN pg_catalog.content.genre g ON g.id = gfw.genre_id
        WHERE gfw.film_work_id = f.id
    ) AS genres
FROM pg_catalog.content.film_work f;

INSERT OVERWRITE dim_users
SELECT
    CAST(u.id AS VARCHAR(36)) AS user_id,
    u.gender,
    u.age_group,
    u.country,
    concat_ws('_', coalesce(u.gender,'X'), coalesce(u.age_group,'X'), coalesce(u.country,'X')) AS segment_code,
    u.created_at AS registered_at,
    u.is_demo
FROM pg_catalog.auth.users u;

INSERT OVERWRITE dim_date
SELECT
    d.`date`,
    d.year,
    d.quarter,
    d.month,
    d.day,
    d.day_of_week,
    d.week_of_year,
    d.is_weekend,
    coalesce(d.is_holiday, FALSE) AS is_holiday
FROM pg_catalog.content.date_dimension d;

-- ============================================================
-- 4. Регулярная синхронизация — нативный SUBMIT TASK
--    SCHEDULE EVERY 1 HOUR. На защите перед демо аналитик при
--    необходимости запускает руками: EXECUTE TASK sync_dim_users; ...
-- ============================================================

DROP TASK IF EXISTS sync_dim_films;
SUBMIT TASK sync_dim_films SCHEDULE EVERY (INTERVAL 1 HOUR)
AS INSERT OVERWRITE dim_films
SELECT
    CAST(f.id AS VARCHAR(36)) AS film_id,
    f.title,
    f.type,
    f.creation_date,
    f.rating,
    f.creation_date IS NOT NULL AND f.creation_date > date_sub(current_date(), INTERVAL 30 DAY) AS is_new,
    (
        SELECT array_agg(g.name)
        FROM pg_catalog.content.genre_film_work gfw
        JOIN pg_catalog.content.genre g ON g.id = gfw.genre_id
        WHERE gfw.film_work_id = f.id
    ) AS genres
FROM pg_catalog.content.film_work f;

DROP TASK IF EXISTS sync_dim_users;
SUBMIT TASK sync_dim_users SCHEDULE EVERY (INTERVAL 1 HOUR)
AS INSERT OVERWRITE dim_users
SELECT
    CAST(u.id AS VARCHAR(36)) AS user_id,
    u.gender,
    u.age_group,
    u.country,
    concat_ws('_', coalesce(u.gender,'X'), coalesce(u.age_group,'X'), coalesce(u.country,'X')) AS segment_code,
    u.created_at AS registered_at,
    u.is_demo
FROM pg_catalog.auth.users u;

DROP TASK IF EXISTS sync_dim_genres;
SUBMIT TASK sync_dim_genres SCHEDULE EVERY (INTERVAL 1 HOUR)
AS INSERT OVERWRITE dim_genres
SELECT
    CAST(id AS VARCHAR(36)) AS genre_id,
    name
FROM pg_catalog.content.genre;

-- dim_date растёт ровно на одну строку в сутки — отдельный SUBMIT TASK
-- (без расписания) для ручного запуска через EXECUTE TASK sync_dim_date.
DROP TASK IF EXISTS sync_dim_date;
SUBMIT TASK sync_dim_date
AS INSERT OVERWRITE dim_date
SELECT
    d.`date`,
    d.year, d.quarter, d.month, d.day, d.day_of_week, d.week_of_year,
    d.is_weekend, coalesce(d.is_holiday, FALSE)
FROM pg_catalog.content.date_dimension d;

-- ============================================================
-- 5. Materialized views (async refresh — пересчитываются автоматически
--    при изменении источников).
-- ============================================================

-- 5.1 mv_user_activity — для сценария «возврат угасшего пользователя».
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_user_activity
DISTRIBUTED BY HASH(user_id) BUCKETS 4
REFRESH ASYNC
PROPERTIES ("replication_num" = "1")
AS
SELECT
    user_id,
    count(*) AS watches_last_30d,
    count(*) >= 12 AS was_active_last_month,    -- ≥3 просмотра/неделю ≈ 12+ за 4 недели
    max(client_time) AS last_watch_at
FROM ugc_analytics.user_events
WHERE event_type = 'view'
  AND client_time > date_sub(now(), INTERVAL 30 DAY)
GROUP BY user_id;

-- 5.2 mv_user_top_genres — компаньон win-back: top-3 жанра пользователя.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_user_top_genres
DISTRIBUTED BY HASH(user_id) BUCKETS 4
REFRESH ASYNC
PROPERTIES ("replication_num" = "1")
AS
WITH user_genre_views AS (
    SELECT
        e.user_id,
        g AS genre,
        count(*) AS views
    FROM ugc_analytics.user_events e
    JOIN ugc_analytics.dim_films f ON f.film_id = e.film_id
    CROSS JOIN unnest(f.genres) AS t(g)
    WHERE e.event_type = 'view'
      AND e.client_time > date_sub(now(), INTERVAL 30 DAY)
    GROUP BY e.user_id, g
),
ranked AS (
    SELECT user_id, genre, views,
           row_number() OVER (PARTITION BY user_id ORDER BY views DESC) AS rn
    FROM user_genre_views
)
SELECT user_id, array_agg(genre) AS top_genres
FROM ranked
WHERE rn <= 3
GROUP BY user_id;

-- 5.3 mv_segment_film_activity — для сценария «тренд в сегменте».
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_segment_film_activity
DISTRIBUTED BY HASH(film_id) BUCKETS 4
REFRESH ASYNC
PROPERTIES ("replication_num" = "1")
AS
SELECT
    date(e.client_time) AS bucket_date,
    u.segment_code AS segment,
    e.film_id,
    count(*) AS views_24h,
    count(DISTINCT e.user_id) AS viewer_count_24h
FROM ugc_analytics.user_events e
JOIN ugc_analytics.dim_users u ON u.user_id = e.user_id
WHERE e.event_type = 'view'
  AND e.client_time > date_sub(now(), INTERVAL 1 DAY)
GROUP BY date(e.client_time), u.segment_code, e.film_id;

-- 5.4 mv_film_watch_hourly — общий MV (часовые агрегаты), используется
--     и в Superset, и в произвольных правилах.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_film_watch_hourly
DISTRIBUTED BY HASH(film_id) BUCKETS 4
REFRESH ASYNC
PROPERTIES ("replication_num" = "1")
AS
SELECT
    date_trunc('hour', client_time) AS bucket_hour,
    film_id,
    count(*) AS views,
    count(DISTINCT user_id) AS unique_viewers
FROM ugc_analytics.user_events
WHERE event_type = 'view'
GROUP BY date_trunc('hour', client_time), film_id;

-- 5.5 mv_weekend_film_activity — демонстрация применения dim_date.
--     Аналитик может писать правило «фильм X стал популярен в выходные».
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_weekend_film_activity
DISTRIBUTED BY HASH(film_id) BUCKETS 4
REFRESH ASYNC
PROPERTIES ("replication_num" = "1")
AS
SELECT
    date(e.client_time) AS bucket_date,
    e.film_id,
    count(*) AS views,
    count(DISTINCT e.user_id) AS unique_viewers
FROM ugc_analytics.user_events e
JOIN ugc_analytics.dim_date d ON d.`date` = date(e.client_time)
WHERE e.event_type = 'view'
  AND d.is_weekend = TRUE
  AND e.client_time > date_sub(now(), INTERVAL 60 DAY)
GROUP BY date(e.client_time), e.film_id;

-- ============================================================
-- 6. Роль alert_reader — её использует alerting-engine
--    (только SELECT на схему ugc_analytics).
-- ============================================================
CREATE USER IF NOT EXISTS 'alert_reader'@'%' IDENTIFIED BY 'alert_reader';
CREATE ROLE IF NOT EXISTS alert_reader;
GRANT SELECT ON ALL TABLES IN DATABASE ugc_analytics TO ROLE alert_reader;
-- В StarRocks materialized views — отдельный объект привилегий: GRANT ... ON
-- ALL TABLES их НЕ покрывает, а правила alerting-engine читают именно mv_*.
GRANT SELECT ON ALL MATERIALIZED VIEWS IN DATABASE ugc_analytics TO ROLE alert_reader;
GRANT alert_reader TO 'alert_reader'@'%';
SET DEFAULT ROLE alert_reader TO 'alert_reader'@'%';

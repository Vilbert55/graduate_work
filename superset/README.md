# superset

Apache Superset 6.1.0 — BI поверх Materialized views `ugc_analytics` в StarRocks.

## Что инициализируется автоматически

1. **Метаданные Superset** — отдельная база `superset` в общей `movies-db`
   (создаёт init-контейнер `superset-db-init` по образцу `sentry-db-init`).
2. **Admin-пользователь** — из переменных `SUPERSET_ADMIN_USER` /
   `SUPERSET_ADMIN_PASSWORD` / `SUPERSET_ADMIN_EMAIL` в `.env`.
3. **Подключение к StarRocks** — datasource `starrocks_analytics`, ходит
   под ролью `alert_reader` (только SELECT на `ugc_analytics.*`).

## Готовые SQL для SQL Lab → Charts

Полностью автоматическое разворачивание дашбордов из YAML/zip — задача недели 3.
В неделе 2 готов 1 минимальный пример; ещё два будут построены руками во
время демо. Все три запроса ниже работают сразу, после первого refresh MV.

### Чарт 1 — почасовая активность по фильмам (Big Number / Line)

```sql
SELECT
    bucket_hour,
    sum(views)          AS total_views,
    sum(unique_viewers) AS total_unique_viewers
FROM ugc_analytics.mv_film_watch_hourly
WHERE bucket_hour > now() - INTERVAL 7 DAY
GROUP BY bucket_hour
ORDER BY bucket_hour;
```

### Чарт 2 — тренд просмотров по сегментам (Bar)

```sql
SELECT
    segment,
    sum(viewer_count_24h) AS viewers
FROM ugc_analytics.mv_segment_film_activity
WHERE bucket_date = current_date
GROUP BY segment
ORDER BY viewers DESC
LIMIT 10;
```

### Чарт 3 — выходные vs будни (Pie)

Задействует `dim_date` (бывший неиспользуемый `content.date_dimension`):

```sql
SELECT
    CASE WHEN d.is_weekend THEN 'weekend' ELSE 'weekday' END AS day_type,
    count(*) AS views
FROM ugc_analytics.user_events e
JOIN ugc_analytics.dim_date d ON d.`date` = date(e.client_time)
WHERE e.event_type = 'view'
  AND e.client_time > now() - INTERVAL 60 DAY
GROUP BY 1;
```

## Запуск

```bash
docker compose up -d superset-db-init movies-superset
# http://localhost:8088  →  admin / admin
```

## Почему не Metabase

Лучше работает на аналитических объёмах (compiled-query DAG); официальный
SQLAlchemy-dialect от StarRocks (`pip install starrocks`); фичи DASHBOARD_RBAC
и DASHBOARD_NATIVE_FILTERS из коробки.

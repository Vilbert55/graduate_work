# Сравнение производительности MongoDB 8 (реплика-сет из 3 нод) и Postgresql 17 в сценариях чтения с агрегациями

## 1. Методика тестирования.

### Архитектура тестового сервиса.

Для проведения исследования реализован отдельный сервис на FastAPI, подключаемый к MongoDB или PostgreSQL через переменную окружения DB_ENGINE.
В сервиси предоставлены следующие тестовые эндпоинты:
- GET /random/user, /random/movie, /random/review – получение случайного ID для тестирования.
- GET /user/{user_id}/likes – список лайков пользователя (оценок фильмам).
- GET /movie/{movie_id}/stats – количество лайков/дизлайков и средняя оценка фильма.
- GET /user/{user_id}/bookmarks – список закладок пользователя.
- POST /film_score – добавление/изменение оценки фильма.
- POST /bookmark – добавление закладки.
- DELETE /bookmark – удаление закладки.

### Тестовые данные и сценарии.

#### Генерируемые объёмы (Сущность -	Количество записей):
- Фильмы (movies)	- 10 000
- Пользователи (users) - 1 000 000
- Оценки (film_scores) - 10 000 000
- Рецензии (reviews) - 500 000
- Закладки (bookmarks) - 5 000 000
- Лайки рецензий - 2 500 000

Все идентификаторы – UUID4. Оценки от 1 до 10. Тексты рецензий – 50–500 символов, случайная дата в пределах двух лет.

#### Индексы

Для обеспечения производительности созданы следующие индексы (одинаковые для обоих хранилищ):
Коллекция/таблица - Индекс(ы):
- film_scores	- user_id; movie_id; (movie_id, score)
- reviews	- (movie_id, created_at DESC)
- bookmarks	- user_id
- review_likes	- review_id

## 2. Инструкция по запуску тестирования

### Требования
- `docker compose` для разворачивания тестовых экземпляров СУБД и генерации данных потребуется `docker compose`;
- `Python 3.12+` для запуска скрипта замера производительности;


### 1) MongoDB 

#### Поднять тестовый кластер MongoDB, сгенерировать и загрузить тестовые данные:
```bash
docker compose -f database_research/mongo_cluster/docker-compose.yml up -d --build && docker logs -f mongo-loader
```

#### Проверка загрузки данных:
```bash
docker exec -it mongo1 mongosh --quiet --eval "
  const db = connect('mongodb://localhost:27017/ugc');
  console.log('movies:', db.movies.countDocuments());
  console.log('users:', db.users.countDocuments());
  console.log('film_scores:', db.film_scores.countDocuments());
  console.log('reviews:', db.reviews.countDocuments());
  console.log('bookmarks:', db.bookmarks.countDocuments());
  console.log('review_likes:', db.review_likes.countDocuments());
"
```

#### Запуск теста производительности. Результаты тестирования будут выведены в консоль, можно их сохранить:
```bash
python database_research/performance_test.py --base-url http://localhost:8000 --iterations 1000
```

#### Завершить работу контейнеров тестового кластера MongoDB и удалить тома:
```bash
docker compose -f database_research/mongo_cluster/docker-compose.yml down -v
```

### 2) Postgresql

#### Поднять тестовый Postgresql 17, сгенерировать и загрузить тестовые данные:
```bash
docker compose -f database_research/postgres_cluster/docker-compose.yml up -d --build && docker logs -f postgres-loader
```

#### Проверка загрузки данных:
```bash
docker exec -it postgres psql -U ugc -d ugc -c "
SELECT 'movies' AS t, count(*) FROM movies
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'film_scores', count(*) FROM film_scores
UNION ALL SELECT 'reviews', count(*) FROM reviews
UNION ALL SELECT 'bookmarks', count(*) FROM bookmarks
UNION ALL SELECT 'review_likes', count(*) FROM review_likes;
"
```

#### Запуск теста производительности. Результаты тестирования будут выведены в консоль, можно их сохранить:
```bash
python database_research/performance_test.py --base-url http://localhost:8000 --iterations 1000
```

#### Завершить работу контейнеров тестового Postgresql и удалить тома:
```bash
docker compose -f database_research/postgres_cluster/docker-compose.yml down -v
```


## 3. Результаты и выводы.

После загрузки 10M+ записей проведены тесты (1000 итераций каждый):

| Эндпоинт                | MongoDB avg/P95 (ms) | PostgreSQL avg/P95 (ms) |
|------------------------ |----------------------|-------------------------|
| GET /user/{id}/likes    | 2.75 / 4.24          | 1.75 / 2.13             |
| GET /movie/{id}/stats   | 1.74 / 2.64          | 1.08 / 1.66             |
| GET /user/{id}/bookmarks| 2.11 / 3.31          | 1.59 / 1.94             |
| POST /film_score        | 2.88 / 3.55          | 1.92 / 2.43             |

Однако моно заметить что в целом сам тест (performance_test.py) на MongoВD выполняется заметно быстрее. Причина:
Каждая итерация, например для User Likes, делает два HTTP-запроса:
  - GET /random/user – получить случайный user_id.
  - GET /user/{user_id}/likes – целевой запрос, время которого попадает в статистику.

Измеряется только второй запрос, но первый тоже тратит реальное время.
В MongoDB $sample работает очень быстро, а в PostgreSQL использован ORDER BY RANDOM() LIMIT 1, который на больших таблицах  выполняется значительно дольше. Это можно легко проверить выполнив и там и там отедльно запрос `time curl -s http://localhost:8000/random/user`.

PostgreSQL 17 отработал быстрее во всех тестах в 1.5–1.8 раз. Скорее всего при более тщательной настройке шардирования MongoDB и при более высокой нагрузке (выполнять http запросы параллельно, а не последовательно) и на реальном железе распределённого кластера MongoDB показала бы лучшие результаты. Однако для учебного проекта такие тесты уже избыточны.

Для хранения пользовательского контента в своём проекте выбираю Postgresql.
В любом случае, даже если бы MongoDB выиграла тесты производительности, выбор остановил бы на Postgresql по причинам:
- развёрнутый экземпляр Postgresql уже имеется в проекте;
- необходимые справочники (фильмы и пользователи) уже сразу доступны в этой СУБД;
- простота аналитических запросов – SQL удобнее для агрегаций, сортировок и объединений (рецензии + лайки рецензий). В MongoDB пришлось бы строить pipeline, который сложнее отлаживать;
- лайки, закладки, рецензии естественно ложатся в связанные таблицы - это всё проще реализуется в реляционной СУБД чем в NoSQL;
- дешевизна поддержки: специалисты с экспертностью Postgresql и реляционных СУБД дешевле на рынке труда и их проще найти, чем специалистов MongoDB и NoSQL СУБД в целом;

Минусы решения на Postgresql и преимущества MongoDB:
- Часто меняющаяся схема - если структура лайка или закладки может меняться непредсказуемо, то документная модель Mongo удобнее.
- Горизонтальное масштабирование - в MongoDB проще быстро добавить производительности.

Даже если при использовании Postgresql будет не хватать производительности в запросах чтения и агрегациях, это легко решается кешированием, например с помощью Redis, который кстати так же уже используется в проекте.
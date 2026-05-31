-- Шаблоны писем, которые ожидают правила alerting-service.
-- Создаются ЧЕРЕЗ публичные функции notifications-сервиса — не лезем
-- в его таблицы напрямую.
--
-- Эта миграция alerting-service применяется ПОСЛЕ notifications-service
-- (см. depends_on в docker-compose: movies-alerting-migrations зависит
-- от movies-notifications-migrations).

SELECT notifications.adm_upsert_template(
    p_code := 'winback_recommendation',
    p_name := 'Win-back: возврат угасшего пользователя',
    p_subject_template := '{{ user.first_name | default(user.login) }}, мы соскучились!',
    p_body_template := $body$Привет, {{ user.first_name | default(user.login) }}!

Вы давно не смотрели фильмы у нас. Возможно, вам понравится что-то новое из ваших любимых жанров:
{% if params.top_genres is defined and params.top_genres %}{{ params.top_genres | join(', ') }}{% else %}подборка специально для вас{% endif %}.

Перейдите в каталог и выберите что-нибудь по душе.

— Команда Movies
$body$,
    p_body_format := 'text',
    p_channel := 'email'
);

-- @statement

SELECT notifications.adm_upsert_template(
    p_code := 'segment_trend_recommendation',
    p_name := 'Тренд в сегменте: похожая премьера',
    p_subject_template := 'Премьера, которая может вам понравиться',
    p_body_template := $body$Здравствуйте, {{ user.first_name | default(user.login) }}!

В вашем сегменте сейчас многие смотрят что-то новое. Мы подобрали для вас
похожий релиз, который ещё не успели посмотреть:
  https://movies.local/films/{{ params.trending_film_id | default('') }}

— Команда Movies
$body$,
    p_body_format := 'text',
    p_channel := 'email'
);

-- @statement

SELECT notifications.adm_upsert_template(
    p_code := 'weekend_promo',
    p_name := 'Выходные: подборка популярного',
    p_subject_template := 'Что посмотреть на выходных',
    p_body_template := $body$Привет, {{ user.first_name | default(user.login) }}!

На этих выходных пользователи активно смотрят: {{ params.film_title | default('подборка по тренду') }}.
Присоединяйтесь:
  https://movies.local/films/{{ params.film_id | default('') }}

— Команда Movies
$body$,
    p_body_format := 'text',
    p_channel := 'email'
);

-- Создание базовых шаблонов через adm_upsert_template. (сидинг)

SELECT notifications.adm_upsert_template(
    p_code := 'welcome',
    p_name := 'Приветствие нового пользователя',
    p_subject_template := 'Добро пожаловать на Movies, {{ user.first_name | default(user.login) }}!',
    p_body_template := $body$Привет, {{ user.first_name | default(user.login) }}!

Спасибо за регистрацию на Movies. Теперь вам доступны:
  - поиск фильмов
  - закладки и оценки
  - персональные рекомендации

Если что-то непонятно — пишите в поддержку.

— Команда Movies
$body$,
    p_body_format := 'text',
    p_channel := 'email'
);

-- @statement

SELECT notifications.adm_upsert_template(
    p_code := 'new_film',
    p_name := 'Уведомление о новом фильме',
    p_subject_template := 'Новый фильм: {{ params.film_title }}',
    p_body_template := $body$Здравствуйте, {{ user.first_name | default(user.login) }}!

В каталоге появился новый фильм: «{{ params.film_title }}» ({{ params.film_year }}).
Жанры: {{ params.film_genres | join(', ') }}.

Смотрите подробности на сайте.
$body$,
    p_body_format := 'text',
    p_channel := 'email'
);

-- @statement

SELECT notifications.adm_upsert_template(
    p_code := 'system_announcement',
    p_name := 'Системное объявление (in-app)',
    p_subject_template := '{{ params.title }}',
    p_body_template := $body$<div class="announcement">
  <p>{{ user.first_name | default(user.login) }}, {{ params.message }}</p>
</div>$body$,
    p_body_format := 'html',
    p_channel := 'ws'
);

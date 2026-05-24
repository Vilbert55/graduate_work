from __future__ import annotations

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimeStampedMixin(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDMixin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class DateDimension(models.Model):
    """Статичная таблица измерений дат."""
    date = models.DateField(primary_key=True, verbose_name="Дата")
    year = models.PositiveSmallIntegerField(verbose_name="Год")
    quarter = models.PositiveSmallIntegerField(verbose_name="Квартал")
    month = models.PositiveSmallIntegerField(verbose_name="Месяц")
    day = models.PositiveSmallIntegerField(verbose_name="День")
    day_of_week = models.PositiveSmallIntegerField(verbose_name="День недели")
    week_of_year = models.PositiveSmallIntegerField(verbose_name="Неделя года")
    is_weekend = models.BooleanField(verbose_name="Выходной")
    is_holiday = models.BooleanField(verbose_name="Праздничный день", default=False, null=True)

    class Meta:
        db_table = 'content"."date_dimension'
        verbose_name = "Измерение даты"
        verbose_name_plural = "Измерения дат"

    def __str__(self) -> str:
        return str(self.date)


class Genre(UUIDMixin, TimeStampedMixin):
    name = models.CharField(_('genre'), max_length=255)
    # из за того что дамп данных с урогов практикума сдесь содержит NULL в description,
    # проще поставить null=True чем править дамп:
    description = models.TextField(_('description'), blank=True, null=True)  # noqa: DJ001

    class Meta:
        db_table = 'content"."genre'
        verbose_name = _('genre')
        verbose_name_plural = _('genres')
        ordering = ('name',)

    def __str__(self) -> str:
        return self.name


class Person(UUIDMixin, TimeStampedMixin):
    full_name = models.CharField(_('name'), max_length=255)

    class Meta:
        db_table = 'content"."person'
        verbose_name = _('person')
        verbose_name_plural = _('persons')

    def __str__(self) -> str:
        return self.full_name


class FilmTypes(models.TextChoices):
    MOVIE = 'movie', _('movie')
    TV_SHOW = 'tv show', _('tv show')


class FilmWork(UUIDMixin, TimeStampedMixin):
    title = models.CharField(_('title'), max_length=255)
    # из за того что дамп данных с урогов практикума сдесь содержит NULL в description,
    # проще поставить null=True чем править дамп:
    description = models.TextField(_('description'), blank=True, null=True)  # noqa: DJ001
    creation_date = models.DateField(_('creation date'), blank=True, null=True)
    # из за того что дамп данных с урогов практикума сдесь содержит NULL в rating,
    # проще поставить null=True чем править дамп:
    rating = models.FloatField(
        _('rating'),
        blank=True,
        null=True,
        validators=[
            MinValueValidator(1.0),
            MaxValueValidator(10.0),
        ],
    )
    type = models.CharField(
        _('type'),
        max_length=7,
        choices=FilmTypes.choices,
        default=FilmTypes.MOVIE,
    )
    genres = models.ManyToManyField(
        Genre,
        through='GenreFilmWork',
        verbose_name=_('genres'),
    )
    persons = models.ManyToManyField(Person, through='PersonFilmWork')

    class Meta:
        db_table = 'content"."film_work'
        verbose_name = _('film')
        verbose_name_plural = _('films')
        ordering = ['-creation_date']
        indexes = [
            models.Index(
                fields=['creation_date', 'rating'],
                name='film_work_creation_rating_idx',
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def update_modified(self):
        """Обновляет поле modified вручную."""
        self.modified = timezone.now()
        self.save(update_fields=['modified'])


class GenreFilmWork(UUIDMixin):
    genre: Genre = models.ForeignKey(
        'Genre',
        on_delete=models.CASCADE,
        verbose_name=_('genre'),
    )
    film_work = models.ForeignKey(FilmWork, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'content"."genre_film_work'
        verbose_name = _('genre')
        verbose_name_plural = _('film genres')
        constraints = [
            models.UniqueConstraint(
                fields=['film_work', 'genre'],
                name='film_work_genre_idx',
            ),
        ]

    def __str__(self) -> str:
        return self.genre.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Обновляем поле modified в связанном FilmWork
        self.film_work.update_modified()

    def delete(self, *args, **kwargs):
        film_work = self.film_work
        super().delete(*args, **kwargs)
        film_work.update_modified()


class Roles(models.TextChoices):
    ACTOR = 'actor', _('actor')
    DIRECTOR = 'director', _('director')
    WRITER = 'writer', _('writer')


class PersonFilmWork(UUIDMixin):
    person: Person = models.ForeignKey(
        'Person',
        on_delete=models.CASCADE,
        verbose_name=_('person'),
    )
    film_work = models.ForeignKey(FilmWork, on_delete=models.CASCADE)
    role = models.CharField(
        _('role'),
        max_length=10,
        choices=Roles.choices,
        default=Roles.ACTOR,
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'content"."person_film_work'
        verbose_name = _('person')
        verbose_name_plural = _('film persons')
        constraints = [
            models.UniqueConstraint(
                fields=['film_work', 'person', 'role'],
                name='film_work_person_role_idx',
            ),
        ]

    def __str__(self) -> str:
        return self.person.full_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Обновляем поле modified в связанном FilmWork
        self.film_work.update_modified()

    def delete(self, *args, **kwargs):
        film_work = self.film_work
        super().delete(*args, **kwargs)
        film_work.update_modified()


# Сигналы для обработки массовых операций с ManyToMany
@receiver([post_save, post_delete], sender=GenreFilmWork)
@receiver([post_save, post_delete], sender=PersonFilmWork)
def update_film_work_on_relation_change(instance, **kwargs):
    """
    Обновляет поле modified в FilmWork при изменении связанных объектов.
    Этот сигнал срабатывает даже при массовых операциях.
    """
    instance.film_work.update_modified()

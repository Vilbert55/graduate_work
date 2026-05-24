from typing import TYPE_CHECKING, Any

from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Q
from django.http import JsonResponse
from django.views.generic.detail import BaseDetailView
from django.views.generic.list import BaseListView

from movies.models import FilmWork, Roles


if TYPE_CHECKING:
    from django.core.paginator import Page
    from django.db.models import QuerySet


class MoviesApiMixin:
    model = FilmWork
    http_method_names = ['get']

    @staticmethod
    def get_queryset() -> 'QuerySet[FilmWork]':
        """
        Возвращает QuerySet с аннотациями для кинопроизведений.

        Добавляет к каждому объекту FilmWork следующие аннотации:
          - film_genres: массив названий жанров
          - film_actors: массив имён актёров
          - film_directors: массив имён режиссёров
          - film_writers: массив имён сценаристов

        Returns:
            QuerySet[FilmWork]: QuerySet с аннотированными полями
        """
        return FilmWork.objects.values(
            'id', 'title', 'description', 'creation_date', 'rating', 'type',
        ).annotate(
            film_genres=ArrayAgg(
                'genres__name',
                distinct=True,
                ordering='genres__name',
                filter=Q(genres__name__isnull=False),
            ),
            film_actors=ArrayAgg(
                'persons__full_name',
                distinct=True,
                ordering='persons__full_name',
                filter=Q(personfilmwork__role=Roles.ACTOR),
            ),
            film_directors=ArrayAgg(
                'persons__full_name',
                distinct=True,
                ordering='persons__full_name',
                filter=Q(personfilmwork__role=Roles.DIRECTOR),
            ),
            film_writers=ArrayAgg(
                'persons__full_name',
                distinct=True,
                ordering='persons__full_name',
                filter=Q(personfilmwork__role=Roles.WRITER),
            ),
        ).order_by('-creation_date', 'title')

    @staticmethod
    def format_film(film_dict: dict[str, Any]) -> dict[str, Any]:
        """
        Форматирует данные одного фильма для JSON-ответа.

        Args:
            film_dict: Словарь с данными фильма из QuerySet

        Returns:
            dict[str, Any]: Отформатированные данные фильма
        """
        return {
            'id': str(film_dict['id']),
            'title': film_dict['title'],
            'description': film_dict['description'] or '',
            'creation_date': film_dict['creation_date'].isoformat() if film_dict['creation_date'] else None,
            'rating': float(film_dict['rating']) if film_dict['rating'] is not None else None,
            'type': film_dict['type'],
            'genres': film_dict.get('film_genres') or [],
            'actors': film_dict.get('film_actors') or [],
            'directors': film_dict.get('film_directors') or [],
            'writers': film_dict.get('film_writers') or [],
        }

    @staticmethod
    def render_to_response(context: dict[str, Any], **_response_kwargs) -> JsonResponse:
        """
        Возвращает JSON-ответ с контекстными данными.

        Args:
            context: Словарь с данными для сериализации в JSON
            **response_kwargs: Дополнительные аргументы для JsonResponse

        Returns:
            JsonResponse: JSON-ответ с данными
        """
        return JsonResponse(context, safe=True)


class MoviesListApi(MoviesApiMixin, BaseListView):
    """
    API представление для получения списка кинопроизведений с пагинацией.

    Возвращает JSON-ответ, содержащий:
      - count: общее количество кинопроизведений
      - total_pages: общее количество страниц
      - prev: номер предыдущей страницы (или None)
      - next: номер следующей страницы (или None)
      - results: список кинопроизведений на текущей странице

    Каждое кинопроизведение содержит следующие поля:
      - id: уникальный идентификатор (UUID)
      - title: название кинопроизведения
      - description: описание
      - creation_date: дата создания
      - rating: рейтинг (от 1.0 до 10.0)
      - type: тип ('movie' или 'tv_show')
      - genres: список жанров
      - actors: список актёров
      - directors: список режиссёров
      - writers: список сценаристов
    """
    paginate_by = 50

    def get_context_data(self, *, _object_list=None, **_kwargs) -> dict[str, Any]:
        """
        Подготавливает контекстные данные для передачи в JSON-ответ.

        Args:
            _object_list: Список объектов (не используется, так как работаем с QuerySet)
            **kwargs: Дополнительные именованные аргументы

        Returns:
            Dict[str, Any]: Словарь с данными для JSON-ответа

        Raises:
            Http404: Если запрашивается несуществующая страница
        """  # noqa: DOC502
        queryset = self.get_queryset()
        paginator, page, queryset, _has_other_pages = self.paginate_queryset(
            queryset,
            self.paginate_by,
        )
        page: Page

        results = [self.format_film(film_dict) for film_dict in queryset]

        return {
            'count': paginator.count,
            'total_pages': paginator.num_pages,
            'prev': page.previous_page_number() if page.has_previous() else None,
            'next': page.next_page_number() if page.has_next() else None,
            'results': results,
        }


class MoviesDetailApi(MoviesApiMixin, BaseDetailView):
    """
    API представление для получения детальной информации о кинопроизведении.

    Возвращает JSON-ответ с данными одного кинопроизведения:
      - id: уникальный идентификатор (UUID)
      - title: название кинопроизведения
      - description: описание
      - creation_date: дата создания
      - rating: рейтинг (от 1.0 до 10.0)
      - type: тип ('movie' или 'tv_show')
      - genres: список жанров
      - actors: список актёров
      - directors: список режиссёров
      - writers: список сценаристов
    """

    def get_context_data(self, **_kwargs) -> dict[str, Any]:
        """
        Подготавливает контекстные данные для одного кинопроизведения.

        Returns:
            Dict[str, Any]: Словарь с данными кинопроизведения для JSON-ответа
        """
        return self.format_film(self.object)

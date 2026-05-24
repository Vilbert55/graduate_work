from debug_toolbar.toolbar import debug_toolbar_urls
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path
from django.utils import timezone
from django.views.decorators.http import require_GET


@require_GET
def health_check(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_status = "ok"
    except Exception as e:  # noqa: BLE001
        db_status = f"error: {e!s}"

    return JsonResponse({
        "status": "ok",
        "database": db_status,
        "service": "movies-api",
        "timestamp": timezone.now().isoformat(),
    })


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('movies.api.urls')),
    path('health_check/', health_check, name='health_check'),
    *debug_toolbar_urls(),
]

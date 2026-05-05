from django.urls import path, include
from django.conf import settings
from django.http import FileResponse

def index(request):
    """Serve the single-page frontend."""
    return FileResponse(
        open(settings.STATICFILES_DIRS[0] / "index.html", "rb"),
        content_type="text/html",
    )

urlpatterns = [
    path("", index, name="index"),
    path("api/", include("proofreader.urls")),
]

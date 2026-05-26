from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

# Root redirect helper
def root_redirect(request):
    return redirect("core:dashboard")

urlpatterns = [
    # Django Admin site
    path("admin/", admin.site.urls),
    
    # Root redirect
    path("", root_redirect, name="root_index"),
    
    # App inclusions
    path("", include("core.urls")),
    path("documents/", include("documents.urls")),
    path("api/", include("api.urls")),
    path("analytics/", include("analytics.urls")),
]

# Serve media files in development / local testing environments
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

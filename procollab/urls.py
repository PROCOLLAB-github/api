from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from core import permissions as core_permissions

schema_view = get_schema_view(
    openapi.Info(
        title="ProCollab API",
        default_version="v1",
        description="API for ProCollab",
    ),
    public=True,
    permission_classes=[core_permissions.IsStaffOrReadOnly],
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),
    re_path(
        r"^swagger(?P<format>\.json|\.yaml)$",
        schema_view.without_ui(cache_timeout=0),
        name="schema-json",
    ),
    re_path(
        r"^swagger/$",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    re_path(
        r"^redoc/$", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"
    ),
    path("files/", include("files.urls", namespace="files")),
    path("industries/", include("industries.urls", namespace="industries")),
    path("news/", include("news.urls", namespace="news")),
    path("projects/", include("projects.urls", namespace="projects")),
    path("vacancies/", include("vacancy.urls", namespace="vacancies")),
    path("invites/", include("invites.urls", namespace="invites")),
    path("auth/", include(("users.urls", "users"), namespace="users")),
    path("chats/", include("chats.urls", namespace="chats")),
    path("events/", include("events.urls", namespace="events")),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("", include("metrics.urls", namespace="metrics")),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

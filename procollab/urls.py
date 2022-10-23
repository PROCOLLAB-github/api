from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework.schemas import get_schema_view
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from users.views import VerifyEmail, ResetPassword

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),
    path("industries/", include("industries.urls", namespace="industries")),
    path("news/", include("news.urls", namespace="news")),
    path("projects/", include("projects.urls", namespace="projects")),
    path("vacancies/", include("vacancy.urls", namespace="vacancies")),
    path("auth/", include(("users.urls", "users"), namespace="users")),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    re_path(
        r"^account-confirm-email/",
        VerifyEmail.as_view(),
        name="account_email_verification_sent",
    ),
    re_path(
        r"^account-confirm-email/(?P<key>[-:\w]+)/$",
        VerifyEmail.as_view(),
        name="account_confirm_email",
    ),
    re_path(
        r"^password-reset/",
        ResetPassword.as_view(),
        name="password_reset_sent",
    ),
    re_path(
        r"^password-reset//(?P<key>[-:\w]+)/$",
        ResetPassword.as_view(),
        name="password_reset",
    ),
    path(
        "openapi/",
        get_schema_view(
            title="Procollab API",
            description="API for all things …",
            version="1.0.0",
        ),
        name="openapi-schema",
    ),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

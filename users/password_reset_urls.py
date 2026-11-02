from django.urls import path
from django_rest_passwordreset.views import (
    ResetPasswordConfirm,
    ResetPasswordRequestToken,
    ResetPasswordValidateToken,
)

from core.throttling import PostOnlyScopedRateThrottle

app_name = "password_reset"


class ThrottledResetPasswordRequestToken(ResetPasswordRequestToken):
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "auth_reset_password"

    def get_throttles(self):
        # The updated package overrides DRF's class-based throttle selection.
        # Preserve this endpoint's existing scoped POST limit.
        return [throttle() for throttle in self.throttle_classes]


urlpatterns = [
    path("", ThrottledResetPasswordRequestToken.as_view(), name="reset-password-request"),
    path("confirm/", ResetPasswordConfirm.as_view(), name="reset-password-confirm"),
    path(
        "validate_token/",
        ResetPasswordValidateToken.as_view(),
        name="reset-password-validate",
    ),
]

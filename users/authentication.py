from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication

DEFAULT_LAST_ACTIVITY_THROTTLE_SECONDS = 15 * 60
LAST_ACTIVITY_CACHE_KEY = "users:last_activity:update:{user_id}"


def get_last_activity_cache_key(user_id: int) -> str:
    return LAST_ACTIVITY_CACHE_KEY.format(user_id=user_id)


class ActivityTrackingJWTAuthentication(JWTAuthentication):
    """
    JWT authentication with lightweight user activity tracking.

    `last_activity` is updated at most once per throttle window per user.
    """

    def authenticate(self, request):
        auth_result = super().authenticate(request)
        if auth_result is None:
            return None

        user, token = auth_result
        self._touch_last_activity(user.id)
        return user, token

    def _touch_last_activity(self, user_id: int) -> None:
        raw_throttle = getattr(
            settings,
            "JWT_LAST_ACTIVITY_THROTTLE_SECONDS",
            DEFAULT_LAST_ACTIVITY_THROTTLE_SECONDS,
        )
        try:
            throttle_seconds = int(raw_throttle)
        except (TypeError, ValueError):
            throttle_seconds = DEFAULT_LAST_ACTIVITY_THROTTLE_SECONDS

        if throttle_seconds < 0:
            throttle_seconds = DEFAULT_LAST_ACTIVITY_THROTTLE_SECONDS

        should_update = True
        if throttle_seconds > 0:
            cache_key = get_last_activity_cache_key(user_id)
            should_update = cache.add(cache_key, "1", timeout=throttle_seconds)

        if not should_update:
            return

        user_model = get_user_model()
        user_model.objects.filter(id=user_id).update(last_activity=timezone.now())

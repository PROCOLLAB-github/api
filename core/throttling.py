from rest_framework.throttling import ScopedRateThrottle
from rest_framework.settings import api_settings


class PostOnlyScopedRateThrottle(ScopedRateThrottle):
    def get_rate(self):
        if not getattr(self, "scope", None):
            return None
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)

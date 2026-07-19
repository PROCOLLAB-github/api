from rest_framework.throttling import ScopedRateThrottle


class PostOnlyScopedRateThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)

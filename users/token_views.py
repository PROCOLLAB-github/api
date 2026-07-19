from rest_framework_simplejwt.views import TokenObtainPairView

from core.throttling import PostOnlyScopedRateThrottle


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "token_obtain"

from rest_framework.throttling import ScopedRateThrottle


class TeamMutationScopedRateThrottle(ScopedRateThrottle):
    """Ограничивает только mutation Team, не меняя глобальную throttle policy."""

    rate = "20/min"

    def get_rate(self):
        return self.rate

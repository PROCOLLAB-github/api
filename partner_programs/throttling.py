from rest_framework.throttling import ScopedRateThrottle


class TeamMutationScopedRateThrottle(ScopedRateThrottle):
    """Ограничивает только mutation Team, не меняя глобальную throttle policy."""

    rate = "20/min"

    def get_rate(self):
        return self.rate


class TeamInviteMutationScopedRateThrottle(ScopedRateThrottle):
    """Ограничивает mutation приглашений без глобального DRF throttling."""

    rate = "20/min"

    def get_rate(self):
        return self.rate

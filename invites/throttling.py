from rest_framework.throttling import ScopedRateThrottle


class ProjectInvitationCandidateSearchScopedRateThrottle(ScopedRateThrottle):
    """Ограничивает scoped-поиск без включения глобального DRF throttling."""

    rate = "20/min"

    def get_rate(self):
        return self.rate

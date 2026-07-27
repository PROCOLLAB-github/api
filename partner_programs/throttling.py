from rest_framework.throttling import ScopedRateThrottle

# Roadmap: DEV-051
# Отдельный лимит частого autosave черновика Evaluation.


class PatchOnlyScopedRateThrottle(ScopedRateThrottle):
    """Ограничивает только PATCH, не затрагивая чтение Evaluation."""

    def allow_request(self, request, view):
        if request.method != "PATCH":
            return True
        return super().allow_request(request, view)


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


class TeamInviteCandidateSearchScopedRateThrottle(ScopedRateThrottle):
    """Ограничивает scoped-поиск кандидатов без глобального DRF throttling."""

    rate = "20/min"

    def get_rate(self):
        return self.rate

from django_filters import rest_framework as filters

from invites.models import Invite
from vacancy.filters import project_id_filter


class InviteFilter(filters.FilterSet):
    """Filter for Invite

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        project (int),
        user (default to request.user if not set otherwise) (int),
        user=any (disable user filter)

    Examples:
        ?project=1 equals to .filter(project_id=1)
        (no params passed) equals to .filter(user=request.user)
        ?user=4 equals to .filter(user_id=4)
        ?project=1&user=any equals to .filter(project_id=1)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data = dict(self.data)
        request = kwargs.get("request")
        if request and request.user.is_authenticated:
            user_value = self.data.get("user")
            if isinstance(user_value, list):
                user_value = user_value[0] if user_value else None
            if user_value is None:
                self.data["user"] = request.user.id

    @staticmethod
    def filter_user(queryset, name, value):
        if isinstance(value, list):
            value = value[0] if value else None
        if value in (None, "", "any"):
            return queryset
        return queryset.filter(user_id=value)

    project = filters.Filter(method=project_id_filter)
    user = filters.Filter(method="filter_user")

    class Meta:
        model = Invite
        fields = ("project", "user")

from django_filters import rest_framework as filters

from invites.models import Invite
from vacancy.filters import project_id_filter


def user_id_filter(queryset, name, value):
    return queryset.filter(
        **{
            "user_id": value[0],
        }
    )


class InviteFilter(filters.FilterSet):
    """Filter for Invite

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        project (int), user (default to request.user if not set otherwise) (int)

    Examples:
        ?project=1 equals to .filter(project_id=1)
        (no params passed) equals to .filter(user=request.user)
        ?user=4 equals to .filter(user_id=4)
    """

    def __init__(self, *args, **kwargs):
        """if user filter is not passed, default to request.user"""
        super().__init__(*args, **kwargs)
        if self.data.get("user_id") is None:
            # default filtering by current user
            self.data = dict(self.data)
            self.data["user"] = kwargs.get("request").user.id

        # fixme: if there is no filter, handler may return too much data
        # if user == "any", remove the filter
        if self.data.get("user_id") == "any":
            self.data = dict(self.data)
            self.data.pop("user_id")

    project = filters.Filter(method=project_id_filter)
    user_id = filters.Filter(method=user_id_filter)

    class Meta:
        model = Invite
        fields = ("project", "user_id")

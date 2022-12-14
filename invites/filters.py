from django_filters import rest_framework as filters

from invites.models import Invite
from vacancy.filters import project_id_filter


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
        if self.data.get("user") is None:
            # default filtering by current user
            self.data = dict(self.data)
            self.data["user"] = kwargs.get("request").user.id
        # if user == "any", remove the filter
        if self.data.get("user") == "any":
            self.data = dict(self.data)
            self.data.pop("user")

    project = filters.Filter(method=project_id_filter)

    class Meta:
        model = Invite
        fields = ("project", "user")

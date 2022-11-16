from django_filters import rest_framework as filters

from invites.models import Invite


class InviteFilter(filters.FilterSet):
    """Filter for Invite

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        project (int), is_active (default to True if not set otherwise) (boolean)

    Examples:
        ?project=1 equals to .filter(project_id=1)
        (no params passed) equals to .filter(is_active=True)
        ?is_active=false equals to .filter(is_active=False)
    """

    def __init__(self, *args, **kwargs):
        """if is_active filter is not passed, default to True"""
        super().__init__(*args, **kwargs)
        # if self.data.get("is_active") is None:
        if self.data.get("user") is None:
            # default filtering by current user
            self.data = dict(self.data)
            self.data["user"] = kwargs.get("request").user.id

    class Meta:
        model = Invite
        fields = ("project", "user")

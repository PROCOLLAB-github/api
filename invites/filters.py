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
        super().__init__(*args, **kwargs)
        self.data = dict(self.data)
        request = kwargs.get("request")
        if request and request.user.is_authenticated:
            self.data["user"] = request.user.id

    project = filters.Filter(method=project_id_filter)
    user = filters.NumberFilter(field_name="user_id")

    class Meta:
        model = Invite
        fields = ("project", "user")

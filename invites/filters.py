from django_filters import rest_framework as filters
from rest_framework.exceptions import PermissionDenied

from invites.models import Invite


def _first_filter_value(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


class InviteFilter(filters.FilterSet):
    """Filter for Invite

    Adds filtering to DRF list retrieve views

    Parameters to filter by:
        project (int),
        user (default to request.user if not set otherwise) (int),
        user=any (available only for staff; disables user filter inside already
        visible queryset)

    Examples:
        ?project=1 equals to .filter(project_id=1)
        (no params passed) equals to .filter(user=request.user)
        ?user=4 equals to .filter(user_id=4)
        ?project=1 for project leader equals to all active project invites
        ?user=any for staff equals to all active invites
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data = dict(self.data)
        request = kwargs.get("request")
        if request and request.user.is_authenticated:
            user_value = _first_filter_value(self.data.get("user"))
            project_value = _first_filter_value(self.data.get("project"))
            if user_value is None and project_value in (None, ""):
                self.data["user"] = request.user.id

    def filter_project(self, queryset, name, value):
        value = _first_filter_value(value)
        if value in (None, ""):
            return queryset
        return queryset.filter(project_id=value)

    def filter_user(self, queryset, name, value):
        value = _first_filter_value(value)
        if value == "any":
            user = getattr(getattr(self, "request", None), "user", None)
            if not user or not (user.is_staff or user.is_superuser):
                raise PermissionDenied("Фильтр user=any доступен только staff.")
            return queryset
        if value in (None, ""):
            return queryset
        return queryset.filter(user_id=value)

    project = filters.Filter(method="filter_project")
    user = filters.Filter(method="filter_user")

    class Meta:
        model = Invite
        fields = ("project", "user")

from django.contrib.auth import get_user_model
from projects.models import Project
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from users.models import Expert, Investor, Member, Mentor
from vacancy.models import Vacancy

User = get_user_model()


class MetricsView(APIView):
    """
    Metrics view

    Shows metrics from the database.
    """

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, format=None):
        data = {}

        models = [User, Expert, Investor, Member, Mentor, Project, Vacancy]

        for model in models:
            data = self._update_total_counts(data, model)

        return Response(data)

    def _update_total_counts(self, data, model) -> dict[str, int]:
        """
        Updates the total counts of the given model.

        Args:
            data: dict with data.
            model: model to get count from.

        Returns:
            dict: A dictionary with the updated data.

        For example:
            {
                "total_Investor_count": 3,
            }
        """

        new_data = dict(data)
        new_data[f"total_{model.__name__}_count"] = model.objects.count()

        return new_data

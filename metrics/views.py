from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from metrics.services import collect_metrics_payload


class MetricsView(APIView):
    """
    Metrics view

    Shows metrics from the database.
    """

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, format=None):
        return Response(collect_metrics_payload())

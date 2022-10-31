from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from django.contrib.auth import get_user_model

from users.models import Expert, Investor, Member, Mentor

User = get_user_model()


class MetricsView(APIView):
    """
    Metrics view

    Represents a view that can be used to get metrics from the database.
    """

    permission_classes = [permissions.IsAdminUser]

    def get(self, request, format=None):

        data = {}

        users_count = User.objects.count()
        data["total_users_count"] = users_count

        members_count = Member.objects.count()
        data["total_members_count"] = members_count

        mentors_count = Mentor.objects.count()
        data["total_mentors_count"] = mentors_count

        experts_count = Expert.objects.count()
        data["total_experts_count"] = experts_count

        investors_count = Investor.objects.count()
        data["total_investors_count"] = investors_count

        return Response(data)

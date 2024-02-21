from django.contrib.auth import get_user_model

from rest_framework import generics, status
from rest_framework.response import Response

from project_rates.models import ProjectScore
from project_rates.serializers import ProjectScoreCreateSerializer, serialize_data_func
from users.permissions import IsExpert

User = get_user_model()


class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpert]

    def create(self, request, *args, **kwargs):
        try:
            data = self.request.data

            user = self.request.user.id
            project_id = self.kwargs.get("project_id")

            criteria_to_get = []
            for criterion in data:
                criterion["user_id"] = user
                criterion["project_id"] = project_id
                criteria_to_get.append(criterion["criterion_id"])

            serializer = self.get_serializer(data=data, many=True)

            if serializer.is_valid():
                serialize_data_func(criteria_to_get, data)
                ProjectScore.objects.bulk_create(
                    [ProjectScore(**score) for score in data]
                )

                return Response({"success": True}, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

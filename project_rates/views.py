from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from rest_framework import generics, status
from rest_framework.response import Response

from project_rates.constants import RatesRequestData
from project_rates.services import (
    get_querysets,
    serialize_project_criterias,
    count_scored_criterias,
)
from project_rates.models import ProjectScore
from project_rates.pagination import RateProjectsPagination
from project_rates.serializers import (
    ProjectScoreCreateSerializer,
    ProjectScoreGetSerializer,
)
from users.models import Expert
from users.permissions import IsExpert, IsExpertPost

User = get_user_model()


class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpertPost]

    def get_needed_data(self) -> tuple[dict, list[int]]:
        data = self.request.data
        user_id = self.request.user.id
        project_id = self.kwargs.get("project_id")

        criteria_to_get = [
            criterion["criterion_id"] for criterion in data
        ]  # is needed for validation later

        Expert.objects.get(user__id=user_id, programs__criterias__id=criteria_to_get[0])

        for criterion in data:
            criterion["user"] = user_id
            criterion["project"] = project_id
            criterion["criteria"] = criterion.pop("criterion_id")

        return data, criteria_to_get

    def create(self, request, *args, **kwargs) -> Response:
        try:
            data, criteria_to_get = self.get_needed_data()

            serializer = ProjectScoreCreateSerializer(
                data=data, criteria_to_get=criteria_to_get, many=True
            )
            serializer.is_valid(raise_exception=True)

            ProjectScore.objects.bulk_create(
                [ProjectScore(**item) for item in serializer.validated_data],
                update_conflicts=True,
                update_fields=["value"],
                unique_fields=["criteria", "user", "project"],
            )

            return Response({"success": True}, status=status.HTTP_201_CREATED)
        except Expert.DoesNotExist:
            return Response(
                {"error": "you have no permission to rate this program"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class RateProjects(generics.ListAPIView):
    serializer_class = ProjectScoreGetSerializer
    permission_classes = [IsExpert]
    pagination_class = RateProjectsPagination

    def get_request_data(self) -> RatesRequestData:
        scored = True if self.request.query_params.get("scored") == "true" else False

        return RatesRequestData(
            program_id=self.kwargs.get("program_id"),
            user=self.request.user,
            view=self,
            scored=scored,
        )

    def get_querysets_dict(self) -> dict[str, QuerySet]:
        return get_querysets(self.get_request_data())

    def serialize_querysets(self) -> list[dict]:
        return serialize_project_criterias(self.get_querysets_dict())

    def get(self, request, *args, **kwargs) -> Response:
        serialized_data = self.serialize_querysets()

        if self.request.query_params.get("scored") == "true":
            [project.update({"is_scored": True}) for project in serialized_data]
        else:
            [count_scored_criterias(project) for project in serialized_data]

        return self.get_paginated_response(serialized_data)


class RateProjectsDetails(RateProjects):
    permission_classes = [IsExpertPost]  # потом решить проблему с этим

    def get_request_data(self) -> RatesRequestData:
        request_data = super().get_request_data()

        project_id = self.request.query_params.get("project_id")
        program_id = self.request.query_params.get("program_id")

        request_data.project_id = int(project_id) if project_id else None
        request_data.program_id = int(program_id) if program_id else None
        return request_data

    def get(self, request, *args, **kwargs):
        try:
            serialized_data = self.serialize_querysets()[0]

            count_scored_criterias(serialized_data)

            return Response(serialized_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

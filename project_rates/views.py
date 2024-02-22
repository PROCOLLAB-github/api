from django.contrib.auth import get_user_model

from rest_framework import generics, status
from rest_framework.response import Response

from projects.models import Project
from project_rates.models import Criteria, ProjectScore
from project_rates.pagination import RateProjectsPagination
from project_rates.serializers import (
    ProjectScoreCreateSerializer,
    CriteriaSerializer,
    ProjectScoreSerializer,
    ProjectScoreGetSerializer,
    serialize_data_func,
)
from users.permissions import IsExpert

User = get_user_model()


class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpert]

    def create(self, request, *args, **kwargs):
        # try:
        data = self.request.data

        user = self.request.user.id
        project_id = self.kwargs.get("project_id")

        criteria_to_get = []
        for criterion in data:
            criterion["user_id"] = user
            criterion["project_id"] = project_id
            criteria_to_get.append(criterion["criterion_id"])

        serialize_data_func(criteria_to_get, data)
        ProjectScore.objects.bulk_create([ProjectScore(**score) for score in data])

        return Response({"success": True}, status=status.HTTP_201_CREATED)


class RateProjects(generics.ListAPIView):
    serializer_class = ProjectScoreGetSerializer
    permission_classes = [IsExpert]
    pagination_class = RateProjectsPagination

    def get(self, request, *args, **kwargs):
        user = self.request.user
        program_id = self.kwargs.get("program_id")

        criterias = Criteria.objects.prefetch_related("partner_program").filter(
            partner_program_id=program_id
        )
        scores = ProjectScore.objects.prefetch_related("criteria").filter(
            criteria__in=criterias.values_list("id", flat=True), user=user
        )
        unpaginated_projects = Project.objects.filter(
            partner_program_profiles__partner_program_id=program_id
        ).distinct()

        projects = self.paginate_queryset(unpaginated_projects)

        criteria_serializer = CriteriaSerializer(data=criterias, many=True)
        scores_serializer = ProjectScoreSerializer(data=scores, many=True)

        criteria_serializer.is_valid()
        scores_serializer.is_valid()

        projects_serializer = self.get_serializer(
            data=projects,
            context={
                "data_criterias": criteria_serializer.data,
                "data_scores": scores_serializer.data,
            },
            many=True,
        )

        projects_serializer.is_valid()

        return self.get_paginated_response(projects_serializer.data)


class RateProjectsDetails(generics.ListAPIView):
    serializer_class = ProjectScoreGetSerializer
    permission_classes = [IsExpert]

    def get(self, request, *args, **kwargs):
        user = self.request.user
        project_id = self.kwargs.get("project_id")

        criterias = Criteria.objects.prefetch_related("partner_program").filter(
            partner_program_id=int(self.request.data.get("program_id"))
        )
        project = Project.objects.filter(id=int(project_id)).first()
        scores = ProjectScore.objects.prefetch_related("criteria").filter(
            criteria__in=criterias.values_list("id", flat=True),
            user=user,
            project=project,
        )

        criterias_data = []
        for criteria in criterias:
            criteria_data = {
                "id": criteria.id,
                "name": criteria.name,
                "description": criteria.description,
                "type": criteria.type,
                "min_value": criteria.min_value,
                "max_value": criteria.max_value,
            }
            criterias_data.append(criteria_data)

        project_scores_data = []
        for project_score in scores:
            project_score_data = {
                "criteria_id": project_score.criteria.id,
                "value": project_score.value,
            }
            project_scores_data.append(project_score_data)

        for score in project_scores_data:
            for criteria in criterias_data:
                if criteria["id"] == score["criteria_id"]:
                    criteria["value"] = score["value"]

        response = {
            "id": project.id,
            "name": project.name,
            "leader": project.leader.id,
            "description": project.description,
            "image_address": project.image_address,
            "industry": project.industry.id,
            "criterias": criterias_data,
        }

        return Response(response, status=200)

from django.contrib.auth import get_user_model
from django.db.models import QuerySet, Count, OuterRef, Subquery, IntegerField

from rest_framework import generics, status
from rest_framework.response import Response

from django_filters import rest_framework as filters

from partner_programs.models import PartnerProgramUserProfile
from projects.models import Project
from projects.filters import ProjectFilter
from project_rates.models import ProjectScore
from project_rates.pagination import RateProjectsPagination
from project_rates.serializers import (
    ProjectScoreCreateSerializer,
    ProjectListForRateSerializer,
)
from users.models import Expert
from users.permissions import IsExpert, IsExpertPost
from vacancy.mapping import ProjectRatedParams, MessageTypeEnum
from vacancy.tasks import send_email

User = get_user_model()


class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpertPost]

    def get_needed_data(self) -> tuple[dict, list[int], str]:
        data = self.request.data
        user_id = self.request.user.id
        project_id = self.kwargs.get("project_id")

        criteria_to_get = [
            criterion["criterion_id"] for criterion in data
        ]  # is needed for validation later

        expert = Expert.objects.get(
            user__id=user_id, programs__criterias__id=criteria_to_get[0]
        )

        for criterion in data:
            criterion["user"] = user_id
            criterion["project"] = project_id
            criterion["criteria"] = criterion.pop("criterion_id")

        return data, criteria_to_get, expert.programs.all().first().name

    def create(self, request, *args, **kwargs) -> Response:
        try:
            data, criteria_to_get, program_name = self.get_needed_data()

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

            project = Project.objects.select_related("leader").get(id=data[0]["project"])

            send_email.delay(
                ProjectRatedParams(
                    message_type=MessageTypeEnum.PROJECT_RATED.value,
                    user_id=project.leader.id,
                    project_name=project.name,
                    project_id=project.id,
                    schema_id=2,
                    program_name=program_name,
                )
            )

            return Response({"success": True}, status=status.HTTP_201_CREATED)
        except Expert.DoesNotExist:
            return Response(
                {"error": "you have no permission to rate this program"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ProjectListForRate(generics.ListAPIView):
    permission_classes = [IsExpert]
    serializer_class = ProjectListForRateSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = ProjectFilter
    pagination_class = RateProjectsPagination

    def get_queryset(self) -> QuerySet[Project]:
        projects_ids = PartnerProgramUserProfile.objects.filter(
            project__isnull=False, partner_program__id=self.kwargs.get("program_id")
        ).values_list("project__id", flat=True)
        # `Count` the easiest way to check for rate exist (0 -> does not exist).
        scored_expert_subquery = ProjectScore.objects.filter(
            project=OuterRef("pk")
        ).values("user__expert__id")[:1]

        return Project.objects.filter(draft=False, id__in=projects_ids).annotate(
            scored=Count("scores"),
            scored_expert_id=Subquery(
                scored_expert_subquery, output_field=IntegerField()
            ),
        )

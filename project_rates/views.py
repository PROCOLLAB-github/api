from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet

from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from django_filters import rest_framework as filters

from partner_programs.models import PartnerProgram, PartnerProgramProject
from partner_programs.serializers import ProgramProjectFilterRequestSerializer
from partner_programs.utils import filter_program_projects_by_field_name
from projects.models import Project
from projects.filters import ProjectFilter
from project_rates.models import Criteria, ProjectScore
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

    def get_needed_data(self) -> tuple[dict, list[int], PartnerProgram]:
        data = self.request.data
        user_id = self.request.user.id
        project_id = self.kwargs.get("project_id")

        criteria_to_get = [
            criterion["criterion_id"] for criterion in data
        ]  # is needed for validation later

        criteria_qs = Criteria.objects.filter(id__in=criteria_to_get).select_related(
            "partner_program"
        )
        partner_program_ids = (
            criteria_qs.values_list("partner_program_id", flat=True).distinct()
        )
        if not criteria_qs.exists():
            raise ValueError("Criteria not found")
        if partner_program_ids.count() != 1:
            raise ValueError("All criteria must belong to the same program")
        program = criteria_qs.first().partner_program

        Expert.objects.get(user__id=user_id, programs=program)

        for criterion in data:
            criterion["user"] = user_id
            criterion["project"] = project_id
            criterion["criteria"] = criterion.pop("criterion_id")

        if not PartnerProgramProject.objects.filter(
            partner_program=program, project_id=project_id
        ).exists():
            raise ValueError("Project is not linked to the program")

        return data, criteria_to_get, program

    def create(self, request, *args, **kwargs) -> Response:
        try:
            data, criteria_to_get, program = self.get_needed_data()
            project_id = data[0]["project"]
            user_id = request.user.id

            serializer = ProjectScoreCreateSerializer(
                data=data, criteria_to_get=criteria_to_get, many=True
            )
            serializer.is_valid(raise_exception=True)

            scores_qs = ProjectScore.objects.filter(
                project_id=project_id, criteria__partner_program=program
            )
            user_has_scores = scores_qs.filter(user_id=user_id).exists()

            if program.max_project_rates:
                distinct_raters = scores_qs.values("user_id").distinct().count()
                if not user_has_scores and distinct_raters >= program.max_project_rates:
                    return Response(
                        {
                            "error": "max project rates reached for this program",
                            "max_project_rates": program.max_project_rates,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            with transaction.atomic():
                ProjectScore.objects.bulk_create(
                    [ProjectScore(**item) for item in serializer.validated_data],
                    update_conflicts=True,
                    update_fields=["value"],
                    unique_fields=["criteria", "user", "project"],
                )

            project = Project.objects.select_related("leader").get(id=project_id)

            send_email.delay(
                ProjectRatedParams(
                    message_type=MessageTypeEnum.PROJECT_RATED.value,
                    user_id=project.leader.id,
                    project_name=project.name,
                    project_id=project.id,
                    schema_id=2,
                    program_name=program.name,
                )
            )

            return Response({"success": True}, status=status.HTTP_201_CREATED)
        except Expert.DoesNotExist:
            return Response(
                {"error": "you have no permission to rate this program"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ProjectListForRate(generics.ListAPIView):
    permission_classes = [IsExpert]
    serializer_class = ProjectListForRateSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = ProjectFilter
    pagination_class = RateProjectsPagination

    def post(self, request, *args, **kwargs):
        """Allow POST with filters in JSON body."""
        return self.list(request, *args, **kwargs)

    def _get_program(self) -> PartnerProgram:
        return PartnerProgram.objects.get(pk=self.kwargs.get("program_id"))

    def _get_filters(self) -> dict:
        """
        Accept filters from JSON body to mirror /partner_programs/<id>/projects/filter/:
        {"filters": {"case": ["Кейс 1"]}}
        """
        if self.request.method != "POST":
            return {}
        data = getattr(self.request, "data", None)
        body_filters = data.get("filters") if isinstance(data, dict) else {}
        return body_filters if isinstance(body_filters, dict) else {}

    def get_queryset(self) -> QuerySet[Project]:
        program = self._get_program()

        filters_serializer = ProgramProjectFilterRequestSerializer(
            data={"filters": self._get_filters()}
        )
        filters_serializer.is_valid(raise_exception=True)
        field_filters = filters_serializer.validated_data.get("filters", {})

        try:
            program_projects_qs = filter_program_projects_by_field_name(
                program, field_filters
            )
        except ValueError as e:
            raise ValidationError({"filters": str(e)})

        project_ids = program_projects_qs.values_list("project_id", flat=True)

        scores_prefetch = Prefetch(
            "scores",
            queryset=ProjectScore.objects.filter(
                criteria__partner_program=program
            ).select_related("user"),
            to_attr="_program_scores",
        )

        return (
            Project.objects.filter(draft=False, id__in=project_ids)
            .annotate(
                rated_count=Count(
                    "scores__user",
                    filter=Q(scores__criteria__partner_program=program),
                    distinct=True,
                )
            )
            .prefetch_related(scores_prefetch)
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["program_max_rates"] = self._get_program().max_project_rates
        return context

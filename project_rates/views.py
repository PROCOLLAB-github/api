from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.exceptions import ValidationError

from django_filters import rest_framework as filters
from django.utils import timezone

from projects.filters import ProjectFilter
from project_rates.pagination import RateProjectsPagination
from project_rates.serializers import (
    ProjectScoreCreateSerializer,
    ProjectListForRateSerializer,
)
from project_rates.services import (
    MaxProjectRatesReached,
    extract_project_rate_filters,
    get_projects_for_rate_queryset,
    get_rate_program,
    submit_project_scores,
)
from users.permissions import IsExpert, IsExpertPost


class RateProject(generics.CreateAPIView):
    serializer_class = ProjectScoreCreateSerializer
    permission_classes = [IsExpertPost]

    def create(self, request, *args, **kwargs) -> Response:
        try:
            submit_project_scores(
                user=request.user,
                project_id=self.kwargs.get("project_id"),
                data=request.data,
            )
            return Response({"success": True}, status=status.HTTP_201_CREATED)
        except PermissionDenied as e:
            return Response({"error": e.detail}, status=e.status_code)
        except MaxProjectRatesReached as e:
            return Response(
                {
                    "error": str(e),
                    "max_project_rates": e.max_project_rates,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except APIException as e:
            return Response(e.detail, status=e.status_code)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class ProjectListForRate(generics.ListAPIView):
    permission_classes = [IsExpert]
    serializer_class = ProjectListForRateSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = ProjectFilter
    pagination_class = RateProjectsPagination

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        # Counts describe the filtered list, before own-status and pagination.
        completed = queryset.filter(_own_completed=True).count()
        self.evaluation_counts = {
            "pending": queryset.count() - completed,
            "completed": completed,
        }
        selected = self.request.query_params.get("evaluation_status")
        if selected not in (None, "pending", "completed"):
            raise ValidationError({"evaluation_status": "Выберите статус оценки."})
        if selected:
            queryset = queryset.filter(_own_completed=selected == "completed")
        return queryset.order_by("pk")

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["evaluation_counts"] = self.evaluation_counts
        response["Cache-Control"] = "no-store"
        return response

    def post(self, request, *args, **kwargs):
        """Allow POST with filters in JSON body."""
        return self.list(request, *args, **kwargs)

    def _get_program(self):
        if not hasattr(self, "_program"):
            self._program = get_rate_program(self.kwargs.get("program_id"))
            self._program.assigned_only = (
                self.request.query_params.get("assigned_only") == "1"
            )
        return self._program

    def get_queryset(self):
        return get_projects_for_rate_queryset(
            program=self._get_program(),
            user=self.request.user,
            field_filters=extract_project_rate_filters(
                self.request.method,
                getattr(self.request, "data", None),
            ),
        )

    def get_serializer_context(self):
        from project_rates.criteria_policy import revision

        context = super().get_serializer_context()
        program = self._get_program()
        context.update(
            program_max_rates=program.max_project_rates,
            criteria_revision=revision(program),
            managed_evaluation=program.required_evaluators is not None,
            program_criteria=list(program.criterias.order_by("pk")),
        )
        if program.required_evaluators is not None:
            context["program_max_rates"] = program.required_evaluators
        if program.assigned_only:
            context.update(
                assigned_program=program,
                is_organizer=program.is_manager(self.request.user),
                now=timezone.now(),
                include_program_fields=(
                    self.request.method == "GET"
                    and bool(self.request.query_params.get("project_id"))
                ),
            )
        return context

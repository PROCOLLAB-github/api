from rest_framework import generics, status
from rest_framework.response import Response

from django_filters import rest_framework as filters

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
from users.models import Expert
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
        except Expert.DoesNotExist:
            return Response(
                {"error": "you have no permission to rate this program"},
                status=status.HTTP_403_FORBIDDEN,
            )
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

    def _get_program(self):
        if not hasattr(self, "_program"):
            self._program = get_rate_program(self.kwargs.get("program_id"))
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
        context = super().get_serializer_context()
        context["program_max_rates"] = self._get_program().max_project_rates
        return context

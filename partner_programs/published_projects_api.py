"""Public legacy-project reader; manager lists and exports retain their permissions."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import AllowAny

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.services.publishing import publish_program_if_due
from projects.models import Project
from projects.serializers import ProjectListSerializer


def published_projects_available(program):
    return bool(
        not program.draft
        and program.solution_storage_mode == "legacy_project"
        and program.publish_projects_after_finish
        and program.datetime_finished <= timezone.now()
    )


class PublishedProjectsPagination(PartnerProgramPagination):
    max_limit = 100


class PublishedProgramProjectsView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = ProjectListSerializer
    pagination_class = PublishedProjectsPagination

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def get_queryset(self):
        program = get_object_or_404(
            PartnerProgram,
            pk=self.kwargs["pk"],
            draft=False,
            solution_storage_mode="legacy_project",
            publish_projects_after_finish=True,
            datetime_finished__lte=timezone.now(),
        )
        publish_program_if_due(program)
        projects = (
            Project.objects.filter(
                Q(program_links__partner_program=program)
                | Q(
                    id__in=PartnerProgramUserProfile.objects.filter(
                        partner_program=program
                    ).values("project_id")
                ),
                draft=False,
                is_public=True,
            )
            .distinct()
            .order_by("pk")
        )
        search = self.request.query_params.get("search", "").strip()
        return projects.filter(name__icontains=search) if search else projects

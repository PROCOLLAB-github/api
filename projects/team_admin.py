"""Admin показывает validation errors; concurrent conflict не становится 500."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse

from partner_programs.models import PartnerProgram, PartnerProgramProject
from projects.models import Project
from projects.team_errors import TeamError


class TeamValidationAdminMixin:
    @transaction.atomic
    def changeform_view(self, request, object_id=None, *args, **kwargs):
        try:
            if request.method == "POST":
                from projects.team_policy import lock_team

                obj = self.get_object(request, object_id) if object_id else None
                project_id = (
                    (obj.pk if isinstance(obj, Project) else obj.project_id)
                    if obj
                    else request.POST.get("project")
                )
                program_id = request.POST.get("partner_program")
                if project_id and str(project_id).isdigit():
                    # До form/inline clean: порядок совпадает с API submission.
                    lock_team(
                        project_id,
                        extra_program_ids=[int(program_id)]
                        if program_id and program_id.isdigit()
                        else [],
                    )
            return super().changeform_view(request, object_id, *args, **kwargs)
        except TeamError as error:
            return JsonResponse(error.detail, status=error.status_code)
        except ValidationError as error:
            return JsonResponse(
                {"code": "team_validation", "detail": error.messages}, status=409
            )

    def delete_view(self, request, *args, **kwargs):
        try:
            return super().delete_view(request, *args, **kwargs)
        except ValidationError as error:
            return JsonResponse(
                {"code": "team_validation", "detail": error.messages}, status=409
            )

    def changelist_view(self, request, *args, **kwargs):
        try:
            return super().changelist_view(request, *args, **kwargs)
        except ValidationError as error:
            return JsonResponse(
                {"code": "team_validation", "detail": error.messages}, status=409
            )

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        objects = list(queryset.order_by("pk"))
        project_ids = {
            obj.pk if isinstance(obj, Project) else obj.project_id for obj in objects
        }
        # Bulk delete сначала берёт все Project, затем все Program в общем порядке.
        list(
            Project.objects.select_for_update().filter(pk__in=project_ids).order_by("pk")
        )
        program_ids = PartnerProgramProject.objects.filter(
            project_id__in=project_ids
        ).values("partner_program_id")
        list(
            PartnerProgram.objects.select_for_update()
            .filter(pk__in=program_ids)
            .order_by("pk")
        )
        for obj in objects:
            obj.delete()

"""Link-scoped program field access and atomic edits/submission."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from partner_programs.models import PartnerProgramFieldValue, PartnerProgramProject
from partner_programs.serializers import (
    PartnerProgramFieldSerializer,
    PartnerProgramFieldValueUpdateSerializer,
)
from partner_programs.services.case_fields import validate_case_before_submission
from projects.models import Project
from projects.access import has_program_link_read_access


class AmbiguousProgramLink(APIException):
    status_code = 409
    default_detail = (
        "Проект связан с несколькими программами. Укажите конкретную связь программы."
    )
    default_code = "ambiguous_program_link"


def get_program_link(link_id, *, for_update=False):
    """Resolve exactly one Project × Program context; optionally lock the link row."""
    links = PartnerProgramProject.objects.select_related("project", "partner_program")
    if for_update:
        links = links.select_for_update(of=("self",))
    return get_object_or_404(links, pk=link_id)


def require_link_leader(link, user):
    """No manager, expert or staff edit override: only the actual project leader."""
    if link.project.leader_id != user.pk:
        raise PermissionDenied("Вы не являетесь лидером этого проекта")


def resolve_legacy_program_link(project_id, user):
    """Legacy writes require exactly one link; never silently choose the first."""
    project = get_object_or_404(Project, pk=project_id)
    if project.leader_id != user.pk:
        raise PermissionDenied("Вы не являетесь лидером этого проекта")
    links = list(project.program_links.order_by("pk").values_list("pk", flat=True)[:2])
    if not links:
        raise ValidationError({"detail": "Проект не привязан ни к одной программе"})
    if len(links) > 1:
        raise AmbiguousProgramLink()
    return links[0]


def program_link_fields(link_id, user):
    """Restricted read, current-program roles only; definitions/values are bulk loaded."""
    link = get_program_link(link_id)
    if not has_program_link_read_access(user, link):
        raise PermissionDenied("У вас нет доступа к полям этой программы проекта.")
    values = dict(link.field_values.values_list("field_id", "value_text"))
    fields = PartnerProgramFieldSerializer(
        link.partner_program.fields.order_by("pk"), many=True
    ).data
    return {
        "program_link_id": link.pk,
        "program_id": link.partner_program_id,
        "project_id": link.project_id,
        "submitted": link.submitted,
        "fields": [{**field, "value": values.get(field["id"])} for field in fields],
    }


@transaction.atomic
def update_program_link_fields(link_id, user, data):
    """Atomic partial update; link lock also serializes this write with submission."""
    link = get_program_link(link_id, for_update=True)
    require_link_leader(link, user)
    if link.partner_program.is_competitive and link.submitted:
        raise ValidationError(
            {
                "detail": "Нельзя изменять значения полей программы после сдачи проекта на проверку."
            }
        )
    # Lock definitions before validation, so removing an option cannot race a choice.
    list(link.partner_program.fields.select_for_update().order_by("pk"))
    serializer = PartnerProgramFieldValueUpdateSerializer(
        data=data, many=True, context={"program": link.partner_program}
    )
    serializer.is_valid(raise_exception=True)
    field_ids = [item["field"].pk for item in serializer.validated_data]
    if len(field_ids) != len(set(field_ids)):
        raise ValidationError({"detail": "В запросе не должны повторяться field_id."})
    try:
        for item in serializer.validated_data:
            PartnerProgramFieldValue.objects.update_or_create(
                program_project=link,
                field=item["field"],
                defaults={"value_text": item.get("value_text")},
            )
    except DjangoValidationError as error:
        raise ValidationError({"detail": error.messages})


@transaction.atomic
def submit_program_project(link_id, user):
    """Freeze a link only after current case validation, under the same lock as PUT."""
    link = get_program_link(link_id, for_update=True)
    require_link_leader(link, user)
    if not link.partner_program.is_competitive:
        raise ValidationError({"detail": "Программа не является конкурсной."})
    if link.submitted:
        raise ValidationError({"detail": "Проект уже был сдан на проверку."})
    if not link.partner_program.is_project_submission_open():
        raise ValidationError({"detail": "Срок подачи проектов в программу завершён."})
    try:
        validate_case_before_submission(link)
    except DjangoValidationError as error:
        raise ValidationError({"detail": error.messages[0]})
    link.submitted = True
    link.datetime_submitted = timezone.now()
    link.save(update_fields=["submitted", "datetime_submitted", "datetime_updated"])

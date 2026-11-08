"""Link-scoped program field access and atomic edits/submission."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from partner_programs.models import PartnerProgramFieldValue, PartnerProgramProject
from partner_programs.project_form import (
    PROJECT_FIELDS,
    field_value,
    project_sections,
    visible_project_fields,
)
from partner_programs.serializers import (
    PartnerProgramFieldSerializer,
    PartnerProgramFieldValueUpdateSerializer,
)
from partner_programs.services.case_fields import validate_case_before_submission
from projects.models import Project
from projects.permissions import has_project_read_involvement


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


def program_link_fields(link_id, user, *, link=None):
    """Restricted read, current-program roles only; definitions/values are bulk loaded."""
    link = link if link is not None and link.pk == link_id else get_program_link(link_id)
    if not has_project_read_involvement(
        user, link.project, program_id=link.partner_program_id
    ):
        raise PermissionDenied("У вас нет доступа к полям этой программы проекта.")
    form = (
        link.submitted_form
        if link.submitted and link.submitted_form
        else form_snapshot(link)
    )
    program = link.partner_program
    submission_open = program.is_project_submission_open()
    return {
        "program_link_id": link.pk,
        "program_id": link.partner_program_id,
        "project_id": link.project_id,
        "submitted": link.submitted,
        "is_competitive": program.is_competitive,
        "submission_open": submission_open,
        "submission_deadline": program.get_project_submission_deadline(),
        "can_submit": program.is_competitive and not link.submitted and submission_open,
        **form,
    }


def form_snapshot(link):
    definitions = list(visible_project_fields(link.partner_program))
    values = (
        dict(link.field_values.values_list("field_id", "value_text")) if link.pk else {}
    )
    return {
        "sections": project_sections(link.partner_program),
        "fields": [
            {**data, "value": field_value(link, field, values)}
            for field, data in zip(
                definitions, PartnerProgramFieldSerializer(definitions, many=True).data
            )
        ],
    }


@transaction.atomic
def update_program_link_fields(link_id, user, data):
    """Atomic partial update; link lock also serializes this write with submission."""
    from projects.team_policy import lock_team

    reference = get_program_link(link_id)
    lock_team(reference.project_id)
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
        data=data,
        many=True,
        context={"program": link.partner_program, "allow_incomplete": True},
    )
    serializer.is_valid(raise_exception=True)
    field_ids = [item["field"].pk for item in serializer.validated_data]
    if len(field_ids) != len(set(field_ids)):
        raise ValidationError({"detail": "В запросе не должны повторяться field_id."})
    visible_ids = set(
        visible_project_fields(link.partner_program).values_list("pk", flat=True)
    )
    if set(field_ids) - visible_ids:
        raise ValidationError(
            {"detail": "Форма программы изменилась. Обновите страницу."}
        )
    try:
        project_changes = {}
        for item in serializer.validated_data:
            attribute = PROJECT_FIELDS.get(item["field"].name)
            if attribute:
                project_changes[attribute] = item.get("value_text") or None
                continue
            if not item.get("value_text"):
                link.field_values.filter(field=item["field"]).delete()
                continue
            PartnerProgramFieldValue.objects.update_or_create(
                program_project=link,
                field=item["field"],
                defaults={"value_text": item.get("value_text")},
            )
        if project_changes:
            Project.objects.filter(pk=link.project_id).update(
                **project_changes, datetime_updated=timezone.now()
            )
    except DjangoValidationError as error:
        raise ValidationError({"detail": error.messages})


@transaction.atomic
def submit_program_project(link_id, user):
    """Freeze a link only after current case validation, under the same lock as PUT."""
    from projects import team_policy

    reference = get_object_or_404(PartnerProgramProject, pk=link_id)
    context = team_policy.lock_team(reference.project_id)
    link = team_policy.resolve_program_context(context.project, link_id)
    require_link_leader(link, user)
    if not link.partner_program.is_competitive:
        raise ValidationError({"detail": "Программа не является конкурсной."})
    if link.submitted:
        raise ValidationError({"detail": "Проект уже был сдан на проверку."})
    if not link.partner_program.is_project_submission_open():
        raise ValidationError({"detail": "Срок подачи проектов в программу завершен."})
    try:
        validate_case_before_submission(link)
    except DjangoValidationError as error:
        raise ValidationError({"detail": error.messages[0]})
    team_policy.validate_submission_team(context.project, link)
    try:
        team_policy.validate_required_program_fields(link)
    except DjangoValidationError as error:
        raise ValidationError(
            {"code": "required_program_fields", "detail": error.messages[0]}
        )
    link.submitted = True
    link.datetime_submitted = timezone.now()
    link.save(update_fields=["submitted", "datetime_submitted", "datetime_updated"])
    Project.objects.filter(pk=link.project_id).update(
        draft=False, datetime_updated=link.datetime_submitted
    )

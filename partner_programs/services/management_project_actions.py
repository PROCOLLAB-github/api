"""Подтверждаемые действия организатора над конкретными связями программы."""

import hashlib
import json
import logging

from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from invites.models import Invite
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.constants import PROGRAM_CASE_FIELD_NAME
from partner_programs.serializers.fields import PartnerProgramFieldValueUpdateSerializer
from partner_programs.services.case_fields import (
    get_program_case_field,
    validate_case_value,
)
from partner_programs.services.management import managed_program
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.workspace import eligible
from projects import team_policy
from projects.models import Project
from projects.team_errors import TeamError

logger = logging.getLogger(__name__)
SALT = "management-project-actions-v1"


class ActionConflict(APIException):
    status_code = 409
    default_detail = (
        "Данные проектов изменились. Проверьте их и подтвердите действие заново."
    )
    default_code = "project_action_conflict"


def load_links(program, ids):
    links = list(
        PartnerProgramProject.objects.filter(partner_program=program, pk__in=ids)
        .select_related("project")
        .prefetch_related("field_values")
        .order_by("pk")
    )
    if len(links) != len(ids):
        raise Http404
    return links


def incompatible_assignments(program, link, case_name):
    scopes = {scope.expert_id: scope for scope in program.expert_case_scopes.all()}
    protected = set(
        ProjectScore.objects.filter(
            project_id=link.project_id, criteria__partner_program=program
        ).values_list("user_id", flat=True)
    )
    return [
        assignment.pk
        for assignment in ProjectExpertAssignment.objects.filter(
            partner_program=program, project_id=link.project_id
        ).select_related("expert")
        if assignment.expert.user_id not in protected
        and not eligible(scopes.get(assignment.expert_id), case_name)
    ]


def submission_errors(program, link, fields):
    if link.submitted:
        return []
    errors = []
    if not program.is_competitive:
        errors.append("В программе нет сдачи конкурсных решений.")
    if link.project.draft:
        errors.append("Заявка в черновике. Сначала завершите ее оформление.")
    values = {value.field_id: value.value_text for value in link.field_values.all()}
    validator = PartnerProgramFieldValueUpdateSerializer()
    for field in fields:
        value = values.get(field.pk)
        if value is None or not str(value).strip():
            if field.is_required or field.name == PROGRAM_CASE_FIELD_NAME:
                errors.append(f"Заполните поле «{field.label}».")
            continue
        try:
            if field.name == PROGRAM_CASE_FIELD_NAME:
                validate_case_value(field, value)
            validator.validate({"field": field, "value_text": value})
        except DjangoValidationError as error:
            errors.append(f"Поле «{field.label}»: {error.messages[0]}")
        except ValidationError as error:
            detail = error.detail
            message = str(detail[0]) if isinstance(detail, list) else str(detail)
            errors.append(f"Поле «{field.label}»: {message}")
    try:
        team_policy.validate_submission_team(link.project, link)
    except TeamError as error:
        errors.append(str(error.detail["detail"]))
    return errors


def snapshot(program, links, fields):
    ids = [link.pk for link in links]
    project_ids = [link.project_id for link in links]
    state = {
        "program": [program.is_competitive, program.datetime_updated],
        "links": [
            [
                link.pk,
                link.project_id,
                link.submitted,
                link.datetime_updated,
                link.project.datetime_updated,
                link.project.draft,
                link.project.leader_id,
            ]
            for link in links
        ],
        "fields": [
            [
                field.pk,
                field.name,
                field.label,
                field.field_type,
                field.is_required,
                field.options,
            ]
            for field in fields
        ],
        "values": list(
            PartnerProgramFieldValue.objects.filter(program_project_id__in=ids)
            .order_by("pk")
            .values_list("pk", "program_project_id", "field_id", "value_text")
        ),
        "scores": list(
            ProjectScore.objects.filter(
                project_id__in=project_ids, criteria__partner_program=program
            )
            .order_by("pk")
            .values_list("pk", "value")
        ),
        "assignments": list(
            ProjectExpertAssignment.objects.filter(
                partner_program=program, project_id__in=project_ids
            )
            .order_by("pk")
            .values_list("pk", "expert_id")
        ),
        "scopes": list(
            program.expert_case_scopes.order_by("pk").values_list(
                "expert_id", "all_cases", "case_names"
            )
        ),
        "teams": list(
            Project.objects.filter(pk__in=project_ids)
            .order_by("pk", "collaborator__user_id")
            .values_list("pk", "collaborator__user_id")
        ),
        "profile_links": list(
            PartnerProgramUserProfile.objects.filter(
                partner_program=program, project_id__in=project_ids
            )
            .order_by("pk")
            .values_list("pk", "user_id", "project_id")
        ),
    }
    return hashlib.sha256(
        json.dumps(state, cls=DjangoJSONEncoder, sort_keys=True).encode()
    ).hexdigest()


def inspect_action(program, links, action, case_name):
    fields = list(program.fields.order_by("pk"))
    # Системное имя берем из canonical helper, а не из подписи поля.
    case_field = get_program_case_field(program)
    if action == "change_case":
        if case_field is None:
            raise ValidationError({"detail": "В программе не настроены кейсы."})
        try:
            validate_case_value(case_field, case_name)
        except DjangoValidationError as error:
            raise ValidationError({"detail": error.messages[0]})
    project_ids = [link.project_id for link in links]
    score_count = ProjectScore.objects.filter(
        project_id__in=project_ids, criteria__partner_program=program
    ).count()
    removed = []
    if action == "change_case":
        removed = incompatible_assignments(program, links[0], case_name)
    elif action == "detach":
        removed = list(
            ProjectExpertAssignment.objects.filter(
                partner_program=program, project_id__in=project_ids
            ).values_list("pk", flat=True)
        )
    items, ready, already = [], 0, 0
    for link in links:
        errors = submission_errors(program, link, fields) if action == "submit" else []
        if action == "change_case" and any(
            value.field_id == case_field.pk and value.value_text == case_name
            for value in link.field_values.all()
        ):
            errors.append("Выберите другой кейс.")
        if action == "submit" and link.submitted:
            already += 1
        elif not errors:
            ready += 1
        items.append({"id": link.pk, "name": link.project.name, "errors": errors})
    result = {
        "items": items,
        "ready_count": ready,
        "already_submitted_count": already,
        "score_count": score_count,
        "removed_assignments_count": len(removed),
        "can_apply": ready > 0 and not any(item["errors"] for item in items),
    }
    return result, snapshot(program, links, fields), removed, case_field


def preview_action(program_id, actor, data):
    program = managed_program(program_id, actor)
    links = load_links(program, data["ids"])
    result, state, _, _ = inspect_action(
        program, links, data["action"], data.get("case_name")
    )
    proof = {
        "actor": actor.pk,
        "program": program.pk,
        "ids": data["ids"],
        "action": data["action"],
        "case": data.get("case_name"),
        "state": state,
    }
    result["preview_token"] = (
        signing.dumps(proof, salt=SALT, compress=True) if result["can_apply"] else None
    )
    return result


@transaction.atomic
def apply_action(program_id, actor, data):
    program = managed_program(program_id, actor)
    references = load_links(program, data["ids"])
    project_ids = sorted({link.project_id for link in references})
    # Порядок совпадает с team policy и удалением участников: Project -> Program -> Link.
    list(
        Project.objects.select_for_update(no_key=True)
        .filter(pk__in=project_ids)
        .order_by("pk")
    )
    program_ids = set(
        PartnerProgramProject.objects.filter(project_id__in=project_ids).values_list(
            "partner_program_id", flat=True
        )
    ) | {program.pk}
    list(
        PartnerProgram.objects.select_for_update()
        .filter(pk__in=program_ids)
        .order_by("pk")
    )
    program = managed_program(program_id, actor)
    list(
        PartnerProgramProject.objects.select_for_update()
        .filter(pk__in=data["ids"])
        .order_by("pk")
    )
    links = load_links(program, data["ids"])
    list(program.fields.select_for_update().order_by("pk"))
    try:
        proof = signing.loads(data["preview_token"], salt=SALT, max_age=600)
    except signing.BadSignature:
        raise ActionConflict()
    expected = {
        "actor": actor.pk,
        "program": program.pk,
        "ids": data["ids"],
        "action": data["action"],
        "case": data.get("case_name"),
    }
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ActionConflict()
    result, state, removed, case_field = inspect_action(
        program, links, data["action"], data.get("case_name")
    )
    if proof.get("state") != state or not result["can_apply"]:
        raise ActionConflict()
    now = timezone.now()
    if data["action"] == "change_case":
        # Явное привилегированное действие; обычные поля сданной заявки остаются заморожены.
        existing = PartnerProgramFieldValue.objects.filter(
            program_project=links[0], field=case_field
        )
        if existing.exists():
            existing.update(value_text=data["case_name"])
        else:
            PartnerProgramFieldValue.objects.bulk_create(
                [
                    PartnerProgramFieldValue(
                        program_project=links[0],
                        field=case_field,
                        value_text=data["case_name"],
                    )
                ]
            )
        ProjectExpertAssignment.objects.filter(pk__in=removed).delete()
        PartnerProgramProject.objects.filter(pk__in=data["ids"]).update(
            datetime_updated=now
        )
    elif data["action"] == "detach":
        # Убираем также старый указатель анкеты: он используется автопубликацией.
        # Регистрация участника и указатели других программ сохраняются.
        PartnerProgramUserProfile.objects.filter(
            partner_program=program, project_id__in=project_ids
        ).update(project=None)
        Invite.objects.filter(program_link_id__in=data["ids"]).delete()
        ProjectExpertAssignment.objects.filter(pk__in=removed).delete()
        PartnerProgramProject.objects.filter(
            partner_program=program, pk__in=data["ids"]
        ).delete()
    else:
        # Только этот endpoint разрешает сдачу после срока, после повторной валидации.
        PartnerProgramProject.objects.filter(
            partner_program=program, pk__in=data["ids"], submitted=False
        ).update(submitted=True, datetime_submitted=now, datetime_updated=now)
    logger.info(
        "Program project action program=%s actor=%s action=%s links=%s",
        program.pk,
        actor.pk,
        data["action"],
        data["ids"],
    )
    return {
        "changed_count": result["ready_count"],
        "already_submitted_count": result["already_submitted_count"],
    }

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.project_form import PROJECT_FIELDS, visible_project_fields
from partner_programs.services.case_fields import (
    get_program_case_field,
    validate_case_value,
)
from projects.models import Collaborator, Project

User = get_user_model()


class ProgramProjectAlreadyApplied(Exception):
    def __init__(self, program_link: PartnerProgramProject):
        self.program_link = program_link
        super().__init__("Проект уже подан в эту программу.")


@dataclass(frozen=True)
class ProgramProjectApplicationResult:
    project: Project
    program_link: PartnerProgramProject


def copy_project(source, *, leader):
    copy = Project.objects.create(
        name=source.name,
        description=source.description,
        region=source.region,
        hidden_score=source.hidden_score,
        actuality=source.actuality,
        target_audience=source.target_audience,
        trl=source.trl,
        implementation_deadline=source.implementation_deadline,
        problem=source.problem,
        industry_id=source.industry_id,
        presentation_address=source.presentation_address,
        image_address=source.image_address,
        leader=leader,
        draft=True,
        is_public=False,
        is_company=source.is_company,
        cover_image_address=source.cover_image_address,
        cover_id=source.cover_id,
    )
    members = []
    for member in source.collaborator_set.all():
        if member.user_id == leader.pk:
            Collaborator.objects.update_or_create(
                user_id=leader.pk,
                project=copy,
                defaults={"role": member.role, "specialization": member.specialization},
            )
        else:
            members.append(
                Collaborator(
                    user_id=member.user_id,
                    project=copy,
                    role=member.role,
                    specialization=member.specialization,
                )
            )
    Collaborator.objects.bulk_create(members)
    return copy


def require_can_apply_project_to_program(
    *,
    program: PartnerProgram,
    user: User,
) -> None:
    if not program.is_project_submission_open():
        raise ValidationError("Срок подачи проектов в программу завершен.")

    if program.is_manager(user):
        return

    if not PartnerProgramUserProfile.objects.filter(
        user=user,
        partner_program=program,
    ).exists():
        raise PermissionDenied("Подача проекта доступна только участникам программы.")


def _validate_unique_program_fields(values_data: list[dict]) -> None:
    seen_field_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for item in values_data:
        field_id = item["field"].id
        if field_id in seen_field_ids:
            duplicate_ids.add(field_id)
        seen_field_ids.add(field_id)
    if duplicate_ids:
        raise ValidationError(
            {
                "program_field_values": f"Есть повторяющиеся field_id: {sorted(duplicate_ids)}"
            }
        )


def _validate_program_field_ownership(
    *,
    program: PartnerProgram,
    values_data: list[dict],
) -> None:
    for item in values_data:
        field = item["field"]
        if field.partner_program_id != program.id:
            raise ValidationError(
                {
                    "program_field_values": f"Поле id={field.id} не относится к этой программе."
                }
            )


@transaction.atomic
def apply_project_to_program(
    *,
    program: PartnerProgram,
    user: User,
    data,
    serializer_class,
) -> ProgramProjectApplicationResult:
    from projects import team_policy

    program = PartnerProgram.objects.select_for_update().get(pk=program.pk)
    if program.solution_storage_mode == "solution":
        raise PermissionDenied("В этой программе заявка создается как решение.")
    require_can_apply_project_to_program(program=program, user=user)

    existing_link = (
        PartnerProgramProject.objects.select_related("project")
        .filter(partner_program=program, project__leader=user)
        .first()
    )
    if existing_link:
        raise ProgramProjectAlreadyApplied(existing_link)

    if program.is_competitive:
        team_policy.validate_program_users(
            program, project_id=None, user_ids={user.pk}, lock=True
        )

    serializer = serializer_class(
        data=data, context={"program": program, "allow_incomplete": True}
    )
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    project_data = validated_data["project"]
    values_data = validated_data.get("program_field_values") or []

    _validate_unique_program_fields(values_data)
    _validate_program_field_ownership(program=program, values_data=values_data)
    if values_data:
        visible_ids = set(visible_project_fields(program).values_list("pk", flat=True))
        if any(item["field"].pk not in visible_ids for item in values_data):
            raise ValidationError(
                {"program_field_values": "Форма программы изменилась. Обновите страницу."}
            )

    with transaction.atomic():
        # Missing case is valid at draft creation; an explicit choice must stay valid
        # even if the definition changed between input validation and this transaction.
        case_field = get_program_case_field(program, for_update=True)
        if case_field is not None:
            for item in values_data:
                if item["field"].pk == case_field.pk and item.get("value_text"):
                    try:
                        validate_case_value(case_field, item.get("value_text"))
                    except DjangoValidationError as error:
                        raise ValidationError({"program_field_values": error.messages})
        source = Project.objects.create(
            leader=user,
            draft=True,
            is_public=False,
            **project_data,
        )
        project = copy_project(source, leader=user) if program.is_competitive else source
        project_changes = {
            PROJECT_FIELDS[item["field"].name]: item.get("value_text") or None
            for item in values_data
            if item["field"].name in PROJECT_FIELDS
        }
        if project_changes:
            Project.objects.filter(pk=project.pk).update(**project_changes)
        program_link = PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
            source_project=source if project.pk != source.pk else None,
        )

        profile = PartnerProgramUserProfile.objects.filter(
            user=user,
            partner_program=program,
        ).first()
        if profile:
            profile.project = project
            profile.save(update_fields=["project"])

        value_objs = [
            PartnerProgramFieldValue(
                program_project=program_link,
                field=item["field"],
                value_text=item.get("value_text") or "",
            )
            for item in values_data
            if item.get("value_text") and item["field"].name not in PROJECT_FIELDS
        ]
        if value_objs:
            PartnerProgramFieldValue.objects.bulk_create(value_objs)

    return ProgramProjectApplicationResult(project=project, program_link=program_link)

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from projects.models import Project

User = get_user_model()


class ProgramProjectAlreadyApplied(Exception):
    def __init__(self, program_link: PartnerProgramProject):
        self.program_link = program_link
        super().__init__("Проект уже подан в эту программу.")


@dataclass(frozen=True)
class ProgramProjectApplicationResult:
    project: Project
    program_link: PartnerProgramProject


def require_can_apply_project_to_program(
    *,
    program: PartnerProgram,
    user: User,
) -> None:
    if not program.is_project_submission_open():
        raise ValidationError("Срок подачи проектов в программу завершён.")

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
            {"program_field_values": f"Есть повторяющиеся field_id: {sorted(duplicate_ids)}"}
        )


def _validate_required_program_fields(
    *,
    program: PartnerProgram,
    values_data: list[dict],
) -> None:
    required_fields = list(
        program.fields.filter(is_required=True).values("id", "label")
    )
    provided_field_ids = {item["field"].id for item in values_data}
    missing_required = [
        field["label"]
        for field in required_fields
        if field["id"] not in provided_field_ids
    ]
    if missing_required:
        raise ValidationError(
            {"program_field_values": f"Не заполнены обязательные поля: {missing_required}"}
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


def apply_project_to_program(
    *,
    program: PartnerProgram,
    user: User,
    data,
    serializer_class,
) -> ProgramProjectApplicationResult:
    require_can_apply_project_to_program(program=program, user=user)

    existing_link = (
        PartnerProgramProject.objects.select_related("project")
        .filter(partner_program=program, project__leader=user)
        .first()
    )
    if existing_link:
        raise ProgramProjectAlreadyApplied(existing_link)

    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    project_data = validated_data["project"]
    values_data = validated_data.get("program_field_values") or []

    _validate_unique_program_fields(values_data)
    _validate_required_program_fields(program=program, values_data=values_data)
    _validate_program_field_ownership(program=program, values_data=values_data)

    with transaction.atomic():
        project = Project.objects.create(
            leader=user,
            draft=True,
            is_public=False,
            **project_data,
        )
        program_link = PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
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
        ]
        if value_objs:
            PartnerProgramFieldValue.objects.bulk_create(value_objs)

    return ProgramProjectApplicationResult(project=project, program_link=program_link)

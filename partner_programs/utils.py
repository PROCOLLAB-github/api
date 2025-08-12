from typing import Dict, List

from django.db.models import Exists, OuterRef

from .models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)


def filter_program_projects_by_field_name(
    program: PartnerProgram, filters: Dict[str, List[str]]
):
    """
    filters: {"field_name": ["val1", "val2"], ...}
    Возвращает queryset PartnerProgramProject, отфильтрованный по условиям.
    Ключи MUST быть field.name (строки). Иначе — ошибка должна быть выброшена на уровне вьюхи.
    """
    qs = PartnerProgramProject.objects.filter(partner_program=program)

    if not filters:
        return qs.select_related("project").distinct()

    for field_name, values in filters.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise ValueError("Не правильное имя поля")

        field_name = field_name.strip()

        field_obj = PartnerProgramField.objects.filter(
            partner_program=program, name=field_name
        ).first()
        if not field_obj:
            raise ValueError(f"Поле {field_name} не найдено в программе с id {program.pk}")

        subq = PartnerProgramFieldValue.objects.filter(
            program_project=OuterRef("pk"), field=field_obj, value_text__in=values
        )
        qs = qs.filter(Exists(subq))

    return qs.select_related("project").distinct()

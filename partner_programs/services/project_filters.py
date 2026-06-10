from django.db.models import Exists, OuterRef

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)


class ProgramProjectFilterError(Exception):
    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(str(detail))


def get_filterable_program_fields(program: PartnerProgram):
    return PartnerProgramField.objects.filter(
        partner_program=program,
        show_filter=True,
    )


def validate_program_project_filters(
    *,
    program: PartnerProgram,
    filters: dict[str, list[str]],
) -> None:
    field_names = list(filters.keys())
    field_qs = PartnerProgramField.objects.filter(
        partner_program=program,
        name__in=field_names,
    )
    field_by_name = {field.name: field for field in field_qs}

    missing = [name for name in field_names if name not in field_by_name]
    if missing:
        raise ProgramProjectFilterError(
            {"detail": f"Поля не найденные в программе: {missing}"}
        )

    for field_name, values in filters.items():
        field_obj = field_by_name[field_name]
        if not field_obj.show_filter:
            raise ProgramProjectFilterError(
                {
                    "detail": (
                        f"Поле '{field_name}' недоступно для фильтрации "
                        "(show_filter=False)."
                    )
                }
            )

        options = field_obj.get_options_list()
        if not options:
            raise ProgramProjectFilterError(
                {"detail": f"Поле '{field_name}' не имеет вариантов (options)."}
            )

        invalid_values = [value for value in values if value not in options]
        if invalid_values:
            raise ProgramProjectFilterError(
                {
                    "detail": f"Неверные значения для поля '{field_name}'.",
                    "invalid": invalid_values,
                }
            )


def get_filtered_program_project_links(
    *,
    program: PartnerProgram,
    filters: dict[str, list[str]],
):
    validate_program_project_filters(program=program, filters=filters)

    qs = PartnerProgramProject.objects.filter(partner_program=program)
    if not filters:
        return qs.select_related("project").distinct()

    for field_name, values in filters.items():
        field = PartnerProgramField.objects.get(
            partner_program=program,
            name=field_name.strip(),
        )
        field_value_exists = PartnerProgramFieldValue.objects.filter(
            program_project=OuterRef("pk"),
            field=field,
            value_text__in=values,
        )
        qs = qs.filter(Exists(field_value_exists))

    return qs.select_related("project").distinct()

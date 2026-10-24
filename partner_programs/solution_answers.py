"""Частичное сохранение черновика под общими блокировками программы и решения."""

from django.db import transaction

from files.models import UserFile
from partner_programs.solution_errors import SolutionError, issue
from partner_programs.solution_models import ProgramSolutionAnswer
from partner_programs.solution_schema import form_data, value_problem
from partner_programs.solution_team import (
    lock_solution,
    require_captain,
    require_mutable,
    require_version,
    advance_version,
)
from partner_programs.solution_files import owned_file_urls, validate_file

UNSET = object()
TEXT_TYPES = ("text", "textarea", "url", "select", "radio")


def cleared_value(field, value):
    return value is None or (
        field["type"] in TEXT_TYPES and isinstance(value, str) and not value.strip()
    )


@transaction.atomic
def update_solution(
    *,
    program_id,
    solution_id,
    actor,
    expected_version,
    expected_form_revision,
    name=UNSET,
    answers=UNSET,
):
    solution = lock_solution(program_id, solution_id, actor)
    require_captain(solution, actor)
    require_mutable(solution)
    require_version(solution, expected_version)
    # Direct model/admin changes use the same program -> definition order.
    list(solution.program.fields.select_for_update().order_by("pk"))
    form = form_data(solution.program)
    if form["revision"] != expected_form_revision:
        raise SolutionError(
            "form_revision_conflict",
            "Форма решения изменилась. Обновите поля.",
            meta={"current_form_revision": form["revision"]},
        )
    definitions = {field["id"]: field for field in form["fields"]}
    changes = [] if answers is UNSET else answers
    seen, problems = set(), []
    for answer in changes:
        field_id, value = answer["field_id"], answer["value"]
        if field_id in seen:
            problems.append(
                issue(
                    f"answers.{field_id}",
                    "duplicate_field",
                    "Поле повторяется в запросе.",
                    field_id,
                )
            )
            continue
        seen.add(field_id)
        field = definitions.get(field_id)
        if field is None:
            problems.append(
                issue(
                    f"answers.{field_id}",
                    "unknown_field",
                    "Поле не относится к этой программе.",
                    field_id,
                )
            )
            continue
        if not cleared_value(field, value):
            problem = value_problem(field, value)
            if problem:
                problems.append(issue(f"answers.{field_id}", *problem, field_id))
    if problems:
        raise SolutionError(
            "invalid_answers", "Проверьте ответы решения.", status=400, errors=problems
        )
    files = [
        (definitions[a["field_id"]], a["value"])
        for a in changes
        if definitions[a["field_id"]]["type"] == "file" and a["value"] is not None
    ]
    # Два решения могут переиспользовать собственные файлы капитана: общий порядок URL.
    list(
        UserFile.objects.select_for_update()
        .filter(pk__in=[value["url"] for _, value in files])
        .order_by("pk")
    )
    owned = owned_file_urls(solution)
    for field, value in files:
        validate_file(solution, field, value, owned_urls=owned)
    for answer in changes:
        field = definitions[answer["field_id"]]
        if cleared_value(field, answer["value"]):
            solution.answers.filter(field_id=field["id"]).delete()
        else:
            ProgramSolutionAnswer.objects.update_or_create(
                solution=solution,
                field_id=field["id"],
                defaults={"value": answer["value"]},
            )
    fields = []
    if name is not UNSET:
        solution.name = name
        fields.append("name")
    return advance_version(solution, fields=fields)

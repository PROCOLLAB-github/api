"""Проверка готовности и атомарная однократная сдача решения."""

import copy

from django.db import transaction
from django.utils import timezone

from files.models import UserFile
from partner_programs.solution_errors import SolutionError, issue
from partner_programs.solution_files import (
    owned_file_urls,
    validate_file,
    MIME_BY_EXTENSION,
)
from partner_programs.solution_schema import form_data, value_problem
from partner_programs.solution_team import (
    lock_solution,
    require_captain,
    require_mutable,
    require_version,
    validate_submission_team,
    advance_version,
)


def answer_issues(form, answers):
    values = {answer["field_id"]: answer["value"] for answer in answers}
    definitions = {field["id"]: field for field in form["fields"]}
    problems = []
    for field in form["fields"]:
        value = values.get(field["id"])
        empty = value is None or (
            field["type"] in ("text", "textarea", "url", "select", "radio")
            and isinstance(value, str)
            and not value.strip()
        )
        if empty:
            if field["required"]:
                problems.append(
                    issue(
                        "answers",
                        "case_required" if field["purpose"] == "case" else "required",
                        "Выберите кейс или задачу."
                        if field["purpose"] == "case"
                        else "Заполните обязательное поле.",
                        field["id"],
                    )
                )
            continue
        problem = value_problem(field, value)
        if problem:
            code, detail = problem
            if field["purpose"] == "case":
                code = "case_unavailable"
            problems.append(issue("answers", code, detail, field["id"]))
    for field_id in values.keys() - definitions.keys():
        problems.append(
            issue(
                "answers",
                "unknown_field",
                "Поле не относится к форме этой программы.",
                field_id,
            )
        )
    return problems


def readiness_issues(solution, form, answers, accepted):
    """Чтение не делает сетевых запросов и не берет writer-блокировки."""
    from projects import team_policy
    from projects.team_errors import TeamError

    problems = []
    if not solution.name.strip():
        problems.append(issue("name", "required", "Укажите название решения."))
    program = solution.program
    try:
        team_policy.validate_program_users(
            program, project_id=None, solution_id=solution.pk, user_ids=accepted
        )
    except TeamError as error:
        problems.append(
            issue("team", str(error.detail["code"]), str(error.detail["detail"]))
        )
    if (
        program.legacy_team_min_size is not None
        and len(accepted) < program.legacy_team_min_size
    ):
        problems.append(
            issue("team", "team_min_size", "В команде недостаточно принятых участников.")
        )
    if (
        program.legacy_team_max_size is not None
        and len(accepted) > program.legacy_team_max_size
    ):
        problems.append(
            issue("team", "team_max_size", "Превышен максимальный размер команды.")
        )
    if not form["is_configured"]:
        problems.append(
            issue(
                "form",
                "form_not_configured",
                "Организатор еще не настроил форму решения.",
            )
        )
    problems.extend(answer_issues(form, answers))
    file_answers = {
        answer["field_id"]: answer["value"]
        for answer in answers
        if isinstance(answer["value"], dict)
        and isinstance(answer["value"].get("url"), str)
    }
    uploads = (
        UserFile.objects.in_bulk([value["url"] for value in file_answers.values()])
        if file_answers
        else {}
    )
    for field in form["fields"]:
        if field["type"] != "file" or field["id"] not in file_answers:
            continue
        upload = uploads.get(file_answers[field["id"]]["url"])
        problem = None
        if upload is None:
            problem = ("file_not_found", "Файл не найден. Загрузите его повторно.")
        elif upload.size > min(
            field["validation"]["max_file_size_bytes"] or 104857600, 104857600
        ):
            problem = ("file_too_large", "Файл превышает допустимый размер.")
        elif (
            field["validation"]["allowed_extensions"]
            and upload.extension.lower() not in field["validation"]["allowed_extensions"]
        ):
            problem = ("file_type_not_allowed", "Выберите разрешенный тип файла.")
        elif (
            upload.detected_mime_type
            and MIME_BY_EXTENSION.get(upload.extension.lower())
            and upload.detected_mime_type
            not in MIME_BY_EXTENSION[upload.extension.lower()]
        ):
            problem = (
                "file_type_mismatch",
                "Содержимое файла не соответствует его типу.",
            )
        if problem:
            problems.append(issue("answers", *problem, field["id"]))
    return problems


def require_open(program):
    if not program.is_project_submission_open():
        raise SolutionError("submission_closed", "Срок сдачи решения завершен.")


@transaction.atomic
def submit_solution(
    *, program_id, solution_id, actor, expected_version, expected_form_revision
):
    solution = lock_solution(program_id, solution_id, actor)
    require_captain(solution, actor)
    if solution.status == "submitted":
        raise SolutionError("already_submitted", "Решение уже сдано.")
    require_mutable(solution)
    require_version(solution, expected_version)
    list(solution.program.fields.select_for_update().order_by("pk"))
    form = form_data(solution.program)
    if form["revision"] != expected_form_revision:
        raise SolutionError(
            "form_revision_conflict",
            "Форма решения изменилась. Обновите поля.",
            meta={"current_form_revision": form["revision"]},
        )
    if not solution.program.is_competitive:
        raise SolutionError("not_competitive", "Эта программа не требует сдачи решения.")
    require_open(solution.program)
    list(solution.members.select_for_update().order_by("pk"))
    try:
        validate_submission_team(solution)
    except SolutionError as error:
        raise SolutionError(
            error.payload["code"],
            error.payload["detail"],
            status=error.status_code,
            errors=[issue("team", error.payload["code"], error.payload["detail"])],
        ) from error
    if not form["is_configured"]:
        raise SolutionError(
            "form_not_configured", "Организатор еще не настроил форму решения."
        )
    answers = [
        dict(field_id=row.field_id, value=row.value)
        for row in solution.answers.order_by("field_id")
    ]
    problems = answer_issues(form, answers)
    if not solution.name.strip():
        problems.insert(0, issue("name", "required", "Укажите название решения."))
    if problems:
        codes = {problem["code"] for problem in problems}
        code = next(
            (code for code in ("case_required", "case_unavailable") if code in codes),
            "required_program_fields" if "required" in codes else "invalid_answers",
        )
        raise SolutionError(
            code, "Проверьте поля решения перед сдачей.", status=400, errors=problems
        )
    values = {answer["field_id"]: answer["value"] for answer in answers}
    files = [
        (field, values[field["id"]])
        for field in form["fields"]
        if field["type"] == "file" and values.get(field["id"]) is not None
    ]
    list(
        UserFile.objects.select_for_update()
        .filter(pk__in=[value["url"] for _, value in files])
        .order_by("pk")
    )
    owned = owned_file_urls(solution)
    for field, value in files:
        validate_file(solution, field, value, owned_urls=owned)
    # Проверка прежнего файла может потребовать I/O; срок проверяется и перед фиксацией.
    from partner_programs.solution_api import solution_data, iso

    data = solution_data(solution, actor)
    stamp = timezone.now()
    deadline = solution.program.get_project_submission_deadline()
    if deadline is not None and stamp > deadline:
        raise SolutionError("submission_closed", "Срок сдачи решения завершен.")
    solution.submission_snapshot = copy.deepcopy(
        dict(
            name=solution.name,
            captain_id=solution.captain_id,
            members=data["team"]["members"],
            form={**form, "is_snapshot": True},
            answers=answers,
            submitted_at=iso(stamp),
        )
    )
    solution.status = "submitted"
    solution.submitted_at = stamp
    return advance_version(
        solution, fields=["status", "submitted_at", "submission_snapshot"]
    )

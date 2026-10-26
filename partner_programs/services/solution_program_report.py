"""The existing safe XLSX writer with actual program-solution identities."""

from collections import Counter

from partner_programs.services.management import participant_rows, person_name
from partner_programs.services.program_report import (
    Report,
    ASSIGNMENT_LABELS,
    score_value,
)


def user_name(user):
    return " ".join(filter(None, (user["first_name"], user["last_name"])))


def write_people(report, program):
    people = report.sheet(
        "Участники",
        [
            "ID участника",
            "Участник",
            "Почта",
            "Регион",
            "Дата регистрации (МСК)",
            "Последняя активность (МСК)",
            "Последний вход (МСК)",
        ],
    )
    answers = report.sheet(
        "Анкеты",
        ["ID регистрации", "ID участника", "Участник", "ID поля", "Поле анкеты", "Ответ"],
    )
    seen = set()
    for profile in participant_rows(program).iterator(chunk_size=500):
        user = profile.user
        if user.pk not in seen:
            report.append(
                people,
                [
                    user.pk,
                    person_name(user),
                    user.email,
                    profile.participant_region,
                    profile.datetime_created,
                    user.last_activity,
                    user.last_login,
                ],
            )
            seen.add(user.pk)
        schema = (
            profile.registration_schema
            if isinstance(profile.registration_schema, dict)
            else {}
        )
        fields = {
            field["id"]: field.get("label", field["id"])
            for field in schema.get("fields", [])
            if isinstance(field, dict) and "id" in field
        }
        data = (
            profile.partner_program_data
            if isinstance(profile.partner_program_data, dict)
            else {}
        )
        for key, value in data.items():
            report.append(
                answers,
                [
                    profile.pk,
                    user.pk,
                    person_name(user),
                    key,
                    fields.get(key, key),
                    value,
                ],
            )


def write_solutions(report, context, *, submitted_only=False, solution_ids=None):
    solutions = report.sheet(
        "Решения",
        [
            "ID решения",
            "ID программы",
            "Решение",
            "Кейс",
            "ID капитана",
            "Капитан",
            "Размер команды",
            "Сдача решения",
            "Создано (МСК)",
            "Сдано (МСК)",
        ],
    )
    teams = report.sheet(
        "Команды", ["ID решения", "Решение", "ID участника", "Участник", "Роль"]
    )
    definitions = report.sheet(
        "Поля формы",
        ["ID решения", "ID поля", "Поле", "Тип", "Назначение", "Обязательно", "Варианты"],
    )
    answers = report.sheet(
        "Ответы решения", ["ID решения", "ID поля", "Поле", "Тип", "Ответ"]
    )
    for solution in context.solutions:
        if solution_ids is not None and solution.pk not in solution_ids:
            continue
        if submitted_only and solution.status != "submitted":
            continue
        row = context.solution_row(solution)
        name = row["application"]["name"]
        team = context.team(solution)
        report.append(
            solutions,
            [
                solution.pk,
                context.program.pk,
                name,
                row["case_name"],
                row["captain"]["user_id"],
                row["captain"]["full_name"],
                len({m["user"]["id"] for m in team}),
                ("Сдано" if solution.status == "submitted" else "Не сдано")
                if context.program.is_competitive
                else "Не требуется",
                solution.created_at,
                solution.submitted_at,
            ],
        )
        for member in team:
            report.append(
                teams,
                [
                    solution.pk,
                    name,
                    member["user"]["id"],
                    user_name(member["user"]),
                    member["role"],
                ],
            )
        fields, values = context.applied_form_and_answers(solution)
        for field in fields:
            report.append(
                definitions,
                [
                    solution.pk,
                    field["id"],
                    field["label"],
                    field["type"],
                    field["purpose"],
                    field["required"],
                    field["options"],
                ],
            )
            if field["id"] in values:
                report.append(
                    answers,
                    [
                        solution.pk,
                        field["id"],
                        field["label"],
                        field["type"],
                        values[field["id"]],
                    ],
                )


def write_evaluation(report, context, *, include_assignments):
    if include_assignments:
        total = Counter(row["expert"]["expert_id"] for row in context.assignments)
        completed = Counter(
            row["expert"]["expert_id"]
            for row in context.assignments
            if row["status"] == "completed"
        )
        experts = report.sheet(
            "Эксперты",
            [
                "ID эксперта",
                "ID пользователя",
                "Эксперт",
                "Почта",
                "Назначений",
                "Выполнено",
            ],
        )
        for expert in context.program.experts.select_related("user").order_by("pk"):
            report.append(
                experts,
                [
                    expert.pk,
                    expert.user_id,
                    person_name(expert.user),
                    expert.user.email,
                    total[expert.pk],
                    completed[expert.pk],
                ],
            )
        assignments = report.sheet(
            "Назначения",
            [
                "ID назначения",
                "ID решения",
                "Решение",
                "ID эксперта",
                "ID пользователя",
                "Эксперт",
                "Статус",
                "Назначено (МСК)",
                "Сдано (МСК)",
            ],
        )
        for row in context.assignments:
            report.append(
                assignments,
                [
                    row["assignment_id"],
                    row["application"]["solution_id"],
                    row["application"]["name"],
                    row["expert"]["expert_id"],
                    row["expert"]["user_id"],
                    row["expert"]["full_name"],
                    ASSIGNMENT_LABELS[row["status"]],
                    row["assigned_at"],
                    row["submitted_at"],
                ],
            )
    criteria_sheet = report.sheet(
        "Критерии", ["ID критерия", "Критерий", "Описание", "Тип", "Минимум", "Максимум"]
    )
    criteria = {criterion.pk: criterion for criterion in context.criteria}
    for criterion in context.criteria:
        report.append(
            criteria_sheet,
            [
                criterion.pk,
                criterion.name,
                criterion.description,
                criterion.type,
                criterion.min_value,
                criterion.max_value,
            ],
        )
    scores = report.sheet(
        "Оценки",
        [
            "ID оценки",
            "ID решения",
            "Решение",
            "ID пользователя эксперта",
            "Эксперт",
            "ID критерия",
            "Критерий",
            "Тип",
            "Значение",
            "Исходное значение",
        ],
    )
    for score in context.score_records:
        criterion = criteria[score["criteria_id"]]
        report.append(
            scores,
            [
                score["pk"],
                score["solution_id"],
                context.application(context.by_id[score["solution_id"]])["name"],
                score["user_id"],
                " ".join(
                    filter(
                        None,
                        (
                            score["user__first_name"],
                            score["user__last_name"],
                            score["user__patronymic"],
                        ),
                    )
                ).strip()
                or "Без имени",
                criterion.pk,
                criterion.name,
                criterion.type,
                score_value(score["value"], criterion.type),
                score["value"],
            ],
        )


def build_solution_program_report(context, kind="program", *, solution_ids=None):
    report = Report()
    if kind == "program":
        overview = context.overview()
        summary = report.sheet("Сводка", ["Показатель", "Значение"])
        for row in [
            ["ID программы", context.program.pk],
            ["Программа", context.program.name],
            ["Сформировано (МСК)", context.now],
            ["Описание", context.program.description],
            ["Начало программы (МСК)", context.program.datetime_started],
            ["Окончание программы (МСК)", context.program.datetime_finished],
            ["Окончание регистрации (МСК)", context.program.datetime_registration_ends],
            [
                "Окончание приема решений (МСК)",
                context.program.get_project_submission_deadline(),
            ],
            ["Окончание оценивания (МСК)", context.program.datetime_evaluation_ends],
            ["Участники", overview["summary"]["participants"]["total"]],
            ["Решения", overview["summary"]["solutions"]["total"]],
            ["Сдано", overview["solution_funnel"]["submitted"]],
            ["Оценено решений", overview["solution_funnel"]["evaluated"]],
            [
                "Заходили на платформу",
                overview["participant_funnel"]["visited_participants"],
            ],
            ["Вступили в команду", overview["participant_funnel"]["with_team"]],
            [
                "Связи между листами",
                "ID решения связывает заявку, команду, поля, ответы, назначения и оценки. "
                "ID участника = ID пользователя.",
            ],
        ]:
            report.append(summary, row)
        write_people(report, context.program)
        cases = report.sheet("Кейсы", ["Кейс", "Решений", "Сдано", "Участников"])
        for row in [
            *overview["cases"]["items"],
            dict(name="Без выбранного кейса", **overview["cases"]["without_case"]),
        ]:
            report.append(
                cases,
                [
                    row["name"],
                    row["solutions_total"],
                    row["submitted"],
                    row["participants_total"],
                ],
            )
        coverage = report.sheet(
            "Заполнение полей",
            [
                "ID поля",
                "Поле",
                "Тип",
                "Назначение",
                "Применимо к решениям",
                "Есть ответ",
                "Обязательно для решений",
                "Нет обязательного ответа",
            ],
        )
        for row in overview["field_coverage"]:
            report.append(
                coverage,
                [
                    row[key]
                    for key in (
                        "field_id",
                        "label",
                        "type",
                        "purpose",
                        "applicable",
                        "answered",
                        "required_applicable",
                        "required_unanswered",
                    )
                ],
            )
        activity = report.sheet("Активность", ["Дата", "Регистраций", "Сдано решений"])
        for row in overview["activity"]:
            report.append(
                activity, [row["date"], row["registrations"], row["submitted_solutions"]]
            )
    if kind in ("program", "solutions", "submitted"):
        write_solutions(
            report,
            context,
            submitted_only=kind == "submitted",
            solution_ids=solution_ids,
        )
    if kind in ("program", "scores"):
        write_evaluation(report, context, include_assignments=kind == "program")
    return report.finish()

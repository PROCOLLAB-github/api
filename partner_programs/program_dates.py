"""Общие проверки календаря для публикации, API и Django-админки."""

DATE_FIELDS = (
    "datetime_started",
    "datetime_registration_ends",
    "datetime_project_submission_ends",
    "datetime_evaluation_ends",
    "datetime_finished",
)


def program_date_errors(values, *, require_complete=False):
    errors = {}
    if require_complete:
        for field in (
            "datetime_started",
            "datetime_finished",
            "datetime_registration_ends",
        ):
            if values.get(field) is None:
                errors[field] = "Укажите дату и время."
    start = values.get("datetime_started")
    finish = values.get("datetime_finished")
    registration = values.get("datetime_registration_ends")
    if start is not None and finish is not None and finish <= start:
        errors["datetime_finished"] = "Окончание программы должно быть позже начала."
    if registration is not None and finish is not None and registration > finish:
        errors[
            "datetime_registration_ends"
        ] = "Регистрация должна завершиться не позже окончания программы."
    return errors


def reopens_program_deadline(before, after, *, now):
    def deadlines(values):
        return (
            values.get("datetime_registration_ends"),
            values.get("datetime_project_submission_ends")
            or values.get("datetime_registration_ends"),
            values.get("datetime_evaluation_ends"),
        )

    return any(
        old is not None and old < now and (new is None or new >= now)
        for old, new in zip(deadlines(before), deadlines(after))
    )

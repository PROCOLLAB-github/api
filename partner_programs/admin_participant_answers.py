import json

from partner_programs.models import ProgramRegistration
from partner_programs.services.registration_answers import registration_answer_rows


def _answer_text(value):
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return ", ".join(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def participant_answer_rows(profile):
    try:
        published = profile.partner_program.registration_config.published
    except ProgramRegistration.DoesNotExist:
        published = None
    return [
        {**row, "text": _answer_text(row["value"])}
        for row in registration_answer_rows(
            profile.registration_schema,
            profile.partner_program_data,
            legacy=profile.partner_program.data_schema,
            published=published,
        )
    ]

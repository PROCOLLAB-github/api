import re

import tablib

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile


ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def export_admin_participants(program: PartnerProgram) -> bytes:
    named_fields = {
        key: field["name"]
        for key, field in program.data_schema.items()
        if "name" in field
    }
    response_data = tablib.Dataset(
        headers=[
            "Имя", "Фамилия", "Отчество", "Почта", "Дата рождения", *named_fields.values()
        ]
    )
    profiles = PartnerProgramUserProfile.objects.filter(
        partner_program=program
    ).select_related("user")
    for profile in profiles.iterator(chunk_size=1000):
        if profile.user is None:
            row = [""] * 5
        else:
            row = [
                profile.user.first_name,
                profile.user.last_name,
                profile.user.patronymic,
                profile.user.email,
                str(profile.user.birthday),
            ]

        row.extend(
            ILLEGAL_CHARACTERS_RE.sub("", profile.partner_program_data.get(key, ""))
            for key in named_fields
        )
        response_data.append(row)

    return response_data.export("xlsx")

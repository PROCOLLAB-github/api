from partner_programs.models import PartnerProgram
from users.models import CustomUser


def render_subject(subject: str, program: PartnerProgram) -> str:
    return subject.replace("{program_name}", program.name)


def render_template_value(
    value: str,
    program: PartnerProgram,
    user: CustomUser,
) -> str:
    return (
        value.replace("{program_name}", program.name)
        .replace("{program_id}", str(program.id))
        .replace("{user_id}", str(user.id))
    )

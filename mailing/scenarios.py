from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable

from partner_programs.models import PartnerProgram
from users.models import CustomUser

FRONTEND_BASE_URL = "https://app.procollab.ru"


class TriggerType(Enum):
    PROGRAM_SUBMISSION_DEADLINE = "program_submission_deadline"


class RecipientRule(Enum):
    ALL_PARTICIPANTS = "all_participants"
    NO_PROJECT_IN_PROGRAM = "no_project_in_program"


ContextBuilder = Callable[[PartnerProgram, CustomUser, date], dict]


@dataclass(frozen=True)
class Scenario:
    code: str
    trigger: TriggerType
    offset_days: int
    template_name: str
    subject: str
    recipient_rule: RecipientRule
    context_builder: ContextBuilder


def _build_submission_deadline_context(offset_days: int) -> ContextBuilder:
    def _builder(program: PartnerProgram, user: CustomUser, deadline_date: date) -> dict:
        deadline_str = deadline_date.strftime("%d.%m.%Y")
        return {
            "preview_text": f"До окончания подачи проектов осталось {offset_days} дней",
            "title": "Пора подать проект",
            "text": (
                f"До окончания подачи проектов в программе «{program.name}» "
                f"осталось {offset_days} дней. "
                f"Пожалуйста, подайте проект и сформируйте команду до {deadline_str}."
            ),
            "button_text": "Подать проект",
            "button_link": f"{FRONTEND_BASE_URL}/office/program/{program.id}",
        }

    return _builder


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        code="program_submission_deadline_minus_10_no_project",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=10,
        template_name="email/generic-template-0.html",
        subject="Procollab | Подача проекта",
        recipient_rule=RecipientRule.NO_PROJECT_IN_PROGRAM,
        context_builder=_build_submission_deadline_context(10),
    ),
)

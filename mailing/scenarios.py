from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable

from partner_programs.models import PartnerProgram
from users.models import CustomUser

FRONTEND_BASE_URL = "https://app.procollab.ru"


class TriggerType(Enum):
    PROGRAM_SUBMISSION_DEADLINE = "program_submission_deadline"
    PROGRAM_REGISTRATION_DATE = "program_registration_date"


class RecipientRule(Enum):
    ALL_PARTICIPANTS = "all_participants"
    NO_PROJECT_IN_PROGRAM = "no_project_in_program"
    NO_PROJECT_IN_PROGRAM_REGISTERED_ON_DATE = "no_project_in_program_registered_on_date"
    PROJECT_NOT_SUBMITTED = "project_not_submitted"


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
        return {
            "preview_text": "Кейс-чемпионат уже стартовал",
            "title": "Время начинать!",
            "text": (
                "Кейс-чемпионат уже стартовал. Скорее заходите на платформу, "
                "создавайте проект и подключайте команду к работе.\n\n"
                "Вас ждет много интересного ⚡"
            ),
            "button_text": "Подать проект",
            "button_link": f"{FRONTEND_BASE_URL}/office/program/{program.id}",
        }

    return _builder


def _build_registration_plus_5_context() -> ContextBuilder:
    def _builder(program: PartnerProgram, user: CustomUser, _ref_date: date) -> dict:
        return {
            "preview_text": "Сделайте первый шаг в программе",
            "title": "Сделать первый шаг",
            "text": (
                "Когда непонятно с чего начать — стоит начать с самого простого. "
                "На раз-два-три: зайти на платформу — создать проект — "
                "пригласить команду.\n\n"
                "И вот, первый шаг уже сделан"
            ),
        }

    return _builder


def _build_project_not_submitted_context(title: str, text: str) -> ContextBuilder:
    def _builder(program: PartnerProgram, user: CustomUser, _ref_date: date) -> dict:
        return {
            "preview_text": title,
            "title": title,
            "text": text,
        }

    return _builder


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        code="program_submission_deadline_minus_10_no_project",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=10,
        template_name="email/generic-template-0.html",
        subject="Время начинать!",
        recipient_rule=RecipientRule.NO_PROJECT_IN_PROGRAM,
        context_builder=_build_submission_deadline_context(10),
    ),
    Scenario(
        code="program_registration_plus_5_no_project",
        trigger=TriggerType.PROGRAM_REGISTRATION_DATE,
        offset_days=5,
        template_name="email/generic-template-0.html",
        subject="Сделать первый шаг",
        recipient_rule=RecipientRule.NO_PROJECT_IN_PROGRAM_REGISTERED_ON_DATE,
        context_builder=_build_registration_plus_5_context(),
    ),
    Scenario(
        code="program_submission_deadline_minus_9_project_not_submitted",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=9,
        template_name="email/generic-template-0.html",
        subject="Кейс-задания опубликованы",
        recipient_rule=RecipientRule.PROJECT_NOT_SUBMITTED,
        context_builder=_build_project_not_submitted_context(
            "Кейс-задания опубликованы",
            "Заходите на платформу, чтобы познакомиться с кейсами первого этапа "
            "кейс-чемпионата. Кейсы загружены в материалы закрытой группы.\n\n"
            "Приступайте к работе уже сегодня, чтобы успеть подготовить итоговое "
            "решение в срок ⚡",
        ),
    ),
    Scenario(
        code="program_submission_deadline_minus_3_project_not_submitted",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=3,
        template_name="email/generic-template-0.html",
        subject="До сдачи итогового решения осталось 3 дня",
        recipient_rule=RecipientRule.PROJECT_NOT_SUBMITTED,
        context_builder=_build_project_not_submitted_context(
            "До сдачи итогового решения осталось 3 дня",
            "Работа в самом разгаре, и мы запускаем обратный отсчет. "
            "Осталось всего 3 дня, чтобы доработать проект, оформить презентацию "
            "и загрузить итоговое решение на платформу.",
        ),
    ),
    Scenario(
        code="program_submission_deadline_minus_1_project_not_submitted",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=1,
        template_name="email/generic-template-0.html",
        subject="1 день до сдачи итогового решения",
        recipient_rule=RecipientRule.PROJECT_NOT_SUBMITTED,
        context_builder=_build_project_not_submitted_context(
            "1 день до сдачи итогового решения",
            "День X совсем скоро. Осталось только внести последние штрихи и "
            "загрузить итоговое решение на платформу.\n\n"
            "По любым техническим вопросам всегда на связи @procollab_support\n\n"
            "Удачи!",
        ),
    ),
)

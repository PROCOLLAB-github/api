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
    PROGRAM_REGISTRATION_END = "program_registration_end"


class RecipientRule(Enum):
    ALL_PARTICIPANTS = "all_participants"
    NO_PROJECT_IN_PROGRAM = "no_project_in_program"
    NO_PROJECT_IN_PROGRAM_REGISTERED_ON_DATE = "no_project_in_program_registered_on_date"
    PROJECT_NOT_SUBMITTED = "project_not_submitted"
    INACTIVE_ACCOUNT_IN_PROGRAM = "inactive_account_in_program"
    INACTIVE_ACCOUNT_IN_PROGRAM_REGISTERED_ON_DATE = (
        "inactive_account_in_program_registered_on_date"
    )


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


def _render_context_value(value: str, program: PartnerProgram, user: CustomUser) -> str:
    return (
        value.replace("{program_name}", program.name)
        .replace("{program_id}", str(program.id))
        .replace("{user_id}", str(user.id))
    )


def _build_context(
    *,
    preview_text: str,
    title: str,
    text: str,
    button_text: str | None = None,
    button_link: str | None = None,
) -> ContextBuilder:
    def _builder(program: PartnerProgram, user: CustomUser, _ref_date: date) -> dict:
        context = {
            "preview_text": _render_context_value(preview_text, program, user),
            "title": _render_context_value(title, program, user),
            "text": _render_context_value(text, program, user),
        }
        if button_text is not None:
            context["button_text"] = _render_context_value(button_text, program, user)
        if button_link is not None:
            context["button_link"] = _render_context_value(button_link, program, user)
        return context

    return _builder


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        code="program_submission_deadline_minus_10_no_project",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=10,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.NO_PROJECT_IN_PROGRAM,
        context_builder=_build_context(
            preview_text="Кейс-чемпионат уже стартовал",
            title="Время начинать!",
            text=(
                "Кейс-чемпионат уже стартовал. Скорее заходите на платформу, "
                "создавайте проект и подключайте команду к работе.\n\n"
                "Вас ждет много интересного ⚡"
            ),
            button_text="Создать проект",
            button_link=f"{FRONTEND_BASE_URL}/office/projects",
        ),
    ),
    Scenario(
        code="program_registration_plus_5_no_project",
        trigger=TriggerType.PROGRAM_REGISTRATION_DATE,
        offset_days=5,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.NO_PROJECT_IN_PROGRAM_REGISTERED_ON_DATE,
        context_builder=_build_context(
            preview_text="Сделать первый шаг",
            title="Сделать первый шаг",
            text=(
                "Когда непонятно с чего начать — стоит начать с самого простого. "
                "Например, зайти на платформу, создать проект или вступить в уже "
                "созданный лидером вашей команды.\n\n"
                "И вот, первый шаг уже сделан!"
            ),
            button_text="Зайти на платформу",
            button_link=f"{FRONTEND_BASE_URL}/office/projects",
        ),
    ),
    Scenario(
        code="program_registration_plus_3_inactive_account",
        trigger=TriggerType.PROGRAM_REGISTRATION_DATE,
        offset_days=3,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.INACTIVE_ACCOUNT_IN_PROGRAM_REGISTERED_ON_DATE,
        context_builder=_build_context(
            preview_text="Поздравляем!",
            title="Поздравляем!",
            text=(
                "Вы зарегистрировались на {program_name}. "
                "Заходите на платформу, чтобы оформить свой профиль участника "
                "и вступить в закрытую группу программы.\n\n"
                "Увидимся на платформе ⚡"
            ),
            button_text="Оформить профиль",
            button_link=f"{FRONTEND_BASE_URL}/office/profile/{{user_id}}/",
        ),
    ),
    Scenario(
        code="program_registration_end_plus_3_inactive_account",
        trigger=TriggerType.PROGRAM_REGISTRATION_END,
        offset_days=3,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.INACTIVE_ACCOUNT_IN_PROGRAM,
        context_builder=_build_context(
            preview_text="Без вас совсем не то",
            title="Без вас совсем не то",
            text=(
                "Мы так обрадовались, увидев вашу регистрацию, но, кажется, "
                "вы еще не заходили на платформу.\n\n"
                "Скорее заходите на procollab, чтобы стать активным участником "
                "программы и забрать максимум полезного для себя ⚡"
            ),
            button_text="Зайти на платформу",
            button_link=f"{FRONTEND_BASE_URL}/office/profile/{{user_id}}/",
        ),
    ),
    Scenario(
        code="program_submission_deadline_minus_9_project_not_submitted",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=9,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.PROJECT_NOT_SUBMITTED,
        context_builder=_build_context(
            preview_text="Кейс-задания опубликованы",
            title="Кейс-задания опубликованы",
            text=(
                "Заходите на платформу, чтобы познакомиться с кейсами первого этапа "
                "кейс-чемпионата. Кейсы загружены в материалы закрытой группы.\n\n"
                "Приступайте к работе уже сегодня, чтобы успеть подготовить итоговое "
                "решение в срок ⚡"
            ),
            button_text="Познакомиться с кейсом",
            button_link=f"{FRONTEND_BASE_URL}/office/program/{{program_id}}",
        ),
    ),
    Scenario(
        code="program_submission_deadline_minus_3_project_not_submitted",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=3,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.PROJECT_NOT_SUBMITTED,
        context_builder=_build_context(
            preview_text="До сдачи итогового решения осталось 3 дня",
            title="До сдачи итогового решения осталось 3 дня",
            text=(
                "Работа в самом разгаре, и мы запускаем обратный отсчет. "
                "Осталось всего 3 дня, чтобы доработать проект, оформить презентацию "
                "и загрузить итоговое решение на платформу."
            ),
            button_text="Загрузить решение",
            button_link=f"{FRONTEND_BASE_URL}/office/projects",
        ),
    ),
    Scenario(
        code="program_submission_deadline_minus_1_project_not_submitted",
        trigger=TriggerType.PROGRAM_SUBMISSION_DEADLINE,
        offset_days=1,
        template_name="email/generic-template-0.html",
        subject="{program_name}: важное сообщение",
        recipient_rule=RecipientRule.PROJECT_NOT_SUBMITTED,
        context_builder=_build_context(
            preview_text="1 день до сдачи итогового решения",
            title="1 день до сдачи итогового решения",
            text=(
                "День X совсем скоро. Осталось только внести последние штрихи и "
                "загрузить итоговое решение на платформу.\n\n"
                "По любым техническим вопросам всегда на связи @procollab_support\n\n"
                "Удачи!"
            ),
            button_text="Загрузить решение",
            button_link=f"{FRONTEND_BASE_URL}/office/program/{{program_id}}",
        ),
    ),
)

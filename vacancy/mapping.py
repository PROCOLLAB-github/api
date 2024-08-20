from enum import Enum
from typing import Literal, TypeAlias, TypedDict, Annotated

EmailTextTypes: TypeAlias = Literal[
    "accepted", "outdated", "responded", "rejected", "registered_program"
]


class MessageTypeEnum(Enum):
    ACCEPTED = "accepted"
    OUTDATED = "outdated"
    RESPONDED = "responded"
    REJECTED = "rejected"

    REGISTERED_PROGRAM_USER = "registered_program"


class BaseEmailCeleryParamsDict(TypedDict):
    message_type: EmailTextTypes
    user_id: int
    schema_id: int  # = 2


class CeleryEmailParamsDict(BaseEmailCeleryParamsDict):
    project_name: str
    project_id: int
    vacancy_role: str


class UserProgramRegisterParamsDict(BaseEmailCeleryParamsDict):
    program_name: str
    program_id: int


message_type_to_button_text: dict[Annotated[str, EmailTextTypes], str] = {
    MessageTypeEnum.ACCEPTED.value: "Посмотреть на проект",
    MessageTypeEnum.RESPONDED.value: "Посмотреть на отклики",
    MessageTypeEnum.OUTDATED.value: "Посмотреть на вакансию",
    MessageTypeEnum.REJECTED.value: "Посмотреть на проект",
    MessageTypeEnum.REGISTERED_PROGRAM_USER.value: "Посмотреть на программу",
}

message_type_to_title: dict[Annotated[str, EmailTextTypes], str] = {
    MessageTypeEnum.ACCEPTED.value: "На ваш отклик ответили",
    MessageTypeEnum.RESPONDED.value: "На вашу вакансию откликнулись",
    MessageTypeEnum.OUTDATED.value: "У вашей вакансии истёк срок годности",
    MessageTypeEnum.REJECTED.value: "На ваш отклик ответили отказом",
    MessageTypeEnum.REGISTERED_PROGRAM_USER.value: "Вы зарегистрировались на программу",
}


def get_link(data: CeleryEmailParamsDict | UserProgramRegisterParamsDict):
    match data["message_type"]:
        case MessageTypeEnum.ACCEPTED.value:
            return f"https://app.procollab.ru/office/projects/{data['project_id']}"
        case MessageTypeEnum.RESPONDED.value:
            return (
                f"https://app.procollab.ru/office/projects/{data['project_id']}/responses"
            )
        case MessageTypeEnum.OUTDATED.value:
            return f"https://app.procollab.ru/office/projects/{data['project_id']}/edit"
        case MessageTypeEnum.REJECTED.value:
            return f"https://app.procollab.ru/office/projects/{data['project_id']}"
        case MessageTypeEnum.REGISTERED_PROGRAM_USER.value:
            return f"https://app.procollab.ru/office/program/{data['program_id']}"


def create_text_for_email(
    data: CeleryEmailParamsDict | UserProgramRegisterParamsDict,
) -> str:
    match data["message_type"]:
        case MessageTypeEnum.ACCEPTED.value:
            return f"""
        Ваш отклик на роль {data["vacancy_role"]} в проекте "{data["project_name"]}" не остался незамеченным.
        Вас готовы принять в команду!
        """
        case MessageTypeEnum.RESPONDED.value:
            return f"На вакансию {data['vacancy_role']} для проекта '{data['project_name']}' оставили отклик."
        case MessageTypeEnum.OUTDATED.value:
            return f"""
            У вакансии {data["vacancy_role"]} для проекта '{data["project_name"]}' истёк срок годности.\n
            Она более не будет показываться в поиске.
    """
        case MessageTypeEnum.REJECTED.value:
            return f"""
            К сожалению, на ваш отклик на вакансию {data['vacancy_role']}
            для проекта '{data['project_name']}' ответили отказом.
    """
        case MessageTypeEnum.REGISTERED_PROGRAM_USER.value:
            return f"""
            Вы успешно зарегистрировались на программу {data['program_name']}
    """

from enum import Enum
from typing import Literal, TypeAlias, TypedDict

EmailTextTypes: TypeAlias = Literal["accepted", "outdated", "responded"]


class MessageTypeEnum(Enum):
    ACCEPTED = "accepted"
    OUTDATED = "outdated"
    RESPONDED = "responded"


class CeleryEmailParamsDict(TypedDict):
    message_type: Literal["accepted", "outdated", "responded"]
    user_id: int
    project_name: str
    project_id: int
    vacancy_role: str
    schema_id: int  # = 2


message_type_to_button_text: dict[EmailTextTypes, str] = {
    MessageTypeEnum.ACCEPTED.value: "Посмотреть на проект",
    MessageTypeEnum.RESPONDED.value: "Посмотреть на отклики",
    MessageTypeEnum.OUTDATED.value: "Посмотреть на вакансию",
}

message_type_to_title: dict[EmailTextTypes, str] = {
    MessageTypeEnum.ACCEPTED.value: "На ваш отклик ответили",
    MessageTypeEnum.RESPONDED.value: "На вашу вакансию откликнулись",
    MessageTypeEnum.OUTDATED.value: "У вашей вакансии истёк срок годности",
}


def get_link(data: CeleryEmailParamsDict):
    if data["message_type"] == "accept":
        return f"https://app.procollab.ru/office/projects/{data['project_id']}"

    elif data["message_type"] == "responded":
        return f"https://app.procollab.ru/office/projects/{data['project_id']}/responses"

    elif data["message_type"] == "outdated":
        return f"https://app.procollab.ru/office/projects/{data['project_id']}/edit"


def create_text_for_email(data: CeleryEmailParamsDict) -> str:
    if data["message_type"] == "accept":
        return f"""
    Ваш отклик на роль {data["vacancy_role"]} в проекте "{data["project_name"]}" не остался незамеченным.
    Вас готовы принять в команду!
    """

    elif data["message_type"] == "responded":
        return f"На вакансию {data['vacancy_role']} для проекта '{data['project_name']}' оставили отклик."

    elif data["message_type"] == "outdated":
        return f"""
        У вакансии {data["vacancy_role"]} для проекта '{data["project_name"]}' истёк срок годности.\n
        Она более не будет показываться в поиске.
"""

from enum import Enum
from typing import Literal, TypeAlias, TypedDict, Annotated

EmailTextTypes: TypeAlias = Literal["accepted", "outdated", "responded", "rejected"]


class MessageTypeEnum(Enum):
    ACCEPTED = "accepted"
    OUTDATED = "outdated"
    RESPONDED = "responded"
    REJECTED = "rejected"


class CeleryEmailParamsDict(TypedDict):
    message_type: EmailTextTypes
    user_id: int
    project_name: str
    project_id: int
    vacancy_role: str
    schema_id: int  # = 2


message_type_to_button_text: dict[Annotated[str, EmailTextTypes], str] = {
    MessageTypeEnum.ACCEPTED.value: "Посмотреть на проект",
    MessageTypeEnum.RESPONDED.value: "Посмотреть на отклики",
    MessageTypeEnum.OUTDATED.value: "Посмотреть на вакансию",
    MessageTypeEnum.REJECTED.value: "Посмотреть на проект",
}

message_type_to_title: dict[Annotated[str, EmailTextTypes], str] = {
    MessageTypeEnum.ACCEPTED.value: "На ваш отклик ответили",
    MessageTypeEnum.RESPONDED.value: "На вашу вакансию откликнулись",
    MessageTypeEnum.OUTDATED.value: "У вашей вакансии истёк срок годности",
    MessageTypeEnum.REJECTED.value: "На ваш отклик ответили отказом",
}


def get_link(data: CeleryEmailParamsDict):
    match data["message_type"]:
        case "accepted":
            return f"https://app.procollab.ru/office/projects/{data['project_id']}"
        case "responded":
            return (
                f"https://app.procollab.ru/office/projects/{data['project_id']}/responses"
            )
        case "outdated":
            return f"https://app.procollab.ru/office/projects/{data['project_id']}/edit"
        case "rejected":
            return f"https://app.procollab.ru/office/projects/{data['project_id']}"


def create_text_for_email(data: CeleryEmailParamsDict) -> str:
    match data["message_type"]:
        case "accepted":
            return f"""
        Ваш отклик на роль {data["vacancy_role"]} в проекте "{data["project_name"]}" не остался незамеченным.
        Вас готовы принять в команду!
        """
        case "responded":
            return f"На вакансию {data['vacancy_role']} для проекта '{data['project_name']}' оставили отклик."
        case "outdated":
            return f"""
            У вакансии {data["vacancy_role"]} для проекта '{data["project_name"]}' истёк срок годности.\n
            Она более не будет показываться в поиске.
    """
        case "rejected":
            return f"""
            К сожалению, на ваш отклик на вакансию {data['vacancy_role']}
            для проекта '{data['project_name']}' ответили отказом.
    """

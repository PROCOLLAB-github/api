from dataclasses import dataclass
from typing import TypedDict, Annotated, TypeAlias

from django.db.models import QuerySet

from mailing.models import MailingSchema
from users.models import CustomUser

UsersType: TypeAlias = QuerySet[CustomUser] | list[CustomUser]


class MailDataDict(TypedDict):
    users: UsersType
    subject: str
    template_string: MailingSchema.template
    template_context: dict


class ContextDataDict(TypedDict):
    text: Annotated[str, "Основной текст письма"]
    title: Annotated[str, "Заголовок письма"]
    button_link: Annotated[str, "Ссылка кнопки"]
    button_text: Annotated[str, "Текст кнопки"]


@dataclass(frozen=True)
class DataToPrepare:
    users_ids: list[int]
    subject: str
    schema_id: int
    context_data: ContextDataDict

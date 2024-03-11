from typing import Literal
from dataclasses import dataclass

from rest_framework.generics import ListAPIView

from users.models import CustomUser

NumericTypes: list[str] = ["int", "float"]

ValidatableTypesNames = Literal[*NumericTypes, "bool", "str"]

VERBOSE_TYPES = (
    ("str", "Текст"),
    ("int", "Целочисленное число"),
    ("float", "Число с плавающей точкой"),
    ("bool", "Да или нет"),
)


@dataclass
class RatesRequestData:
    program_id: int
    user: CustomUser
    view: ListAPIView
    scored: bool | None = None
    project_id: int | None = None

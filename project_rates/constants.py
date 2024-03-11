from typing import Literal
from dataclasses import dataclass

from django.db.models import QuerySet
from rest_framework.generics import ListAPIView

from project_rates.models import Criteria, ProjectScore
from projects.models import Project
from users.models import CustomUser

VERBOSE_TYPES = (
    ("str", "Текст"),
    ("int", "Целочисленное число"),
    ("float", "Число с плавающей точкой"),
    ("bool", "Да или нет"),
)

NumericTypes: list[str] = ["int", "float"]

ValidatableTypesNames = Literal[*NumericTypes, "bool", "str"]


@dataclass(frozen=True)
class RatesQuerySets:
    criterias_queryset: QuerySet[Criteria]
    scores_queryset: QuerySet[ProjectScore]
    projects_queryset: QuerySet[Project]


@dataclass
class RatesRequestData:
    program_id: int
    user: CustomUser
    view: ListAPIView
    scored: bool | None = None
    project_id: int | None = None

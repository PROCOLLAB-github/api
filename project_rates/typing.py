from typing import TypedDict


class CriteriasResponse(TypedDict):
    id: int
    name: str
    description: str
    type: str
    min_value: int | float | None
    max_value: int | float | None


class ProjectScoresResponse(CriteriasResponse):
    value: str

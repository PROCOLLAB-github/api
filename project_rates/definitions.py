from typing import TypedDict


class CriteriasResponse(TypedDict):
    id: int  # noqa A003 VNE003
    name: str
    description: str
    type: str  # noqa A003 VNE003
    min_value: int | float | None
    max_value: int | float | None


class ProjectScoresResponse(CriteriasResponse):
    value: str

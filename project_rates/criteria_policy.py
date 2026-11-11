"""Shared revision and permanent freeze policy for organizer/admin/expert writes."""

import hashlib
import json

from django.utils import timezone
from rest_framework.exceptions import APIException


class CriteriaConflict(APIException):
    status_code = 409

    def __init__(self, code, detail):
        super().__init__({"code": code, "detail": detail})


def definitions(program):
    rows = list(
        program.criterias.order_by("pk").values(
            "id",
            "name",
            "description",
            "type",
            "min_value",
            "max_value",
            "weight_percent",
        )
    )
    for row in rows:
        if row["weight_percent"] is not None:
            row["weight_percent"] = float(row["weight_percent"])
    return rows


def revision(program):
    return hashlib.sha256(
        json.dumps(
            {
                "scoring_mode": program.evaluation_scoring_mode,
                "criteria": definitions(program),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()


def locked(program):
    from project_rates.models import ProjectScore, SolutionScore

    return (
        bool(program.evaluation_criteria_locked_at)
        or ProjectScore.objects.filter(criteria__partner_program=program).exists()
        or SolutionScore.objects.filter(criteria__partner_program=program).exists()
    )


def mark_locked(program):
    from partner_programs.models import PartnerProgram

    if not program.evaluation_criteria_locked_at:
        program.evaluation_criteria_locked_at = timezone.now()
        PartnerProgram.objects.filter(pk=program.pk).update(
            evaluation_criteria_locked_at=program.evaluation_criteria_locked_at
        )


def require_scoring_configuration(program, criteria=None):
    from django.core.exceptions import ValidationError
    from project_rates.scoring import validate_configuration

    try:
        validate_configuration(program, criteria)
    except ValidationError as error:
        raise CriteriaConflict("invalid_criteria", " ".join(error.messages)) from error

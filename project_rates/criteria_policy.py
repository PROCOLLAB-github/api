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
    return list(
        program.criterias.order_by("pk").values(
            "id", "name", "description", "type", "min_value", "max_value"
        )
    )


def revision(program):
    return hashlib.sha256(
        json.dumps(definitions(program), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def locked(program):
    from project_rates.models import ProjectScore

    return (
        bool(program.evaluation_criteria_locked_at)
        or ProjectScore.objects.filter(criteria__partner_program=program).exists()
    )


def mark_locked(program):
    from partner_programs.models import PartnerProgram

    if not program.evaluation_criteria_locked_at:
        program.evaluation_criteria_locked_at = timezone.now()
        PartnerProgram.objects.filter(pk=program.pk).update(
            evaluation_criteria_locked_at=program.evaluation_criteria_locked_at
        )

"""Atomic editing of the shared program criteria, before the first score."""

import math

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from partner_programs.models import PartnerProgram
from partner_programs.serializers.management import StrictFieldsMixin
from partner_programs.services.management import managed_program
from project_rates.criteria_policy import CriteriaConflict, definitions, locked, revision
from project_rates.models import Criteria

SUPPORTED_TYPES = ("int", "bool", "str")


class CriterionWrite(StrictFieldsMixin, serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    name = serializers.CharField(max_length=50)
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default="", max_length=4000
    )
    type = serializers.ChoiceField(choices=(*SUPPORTED_TYPES, "float"))
    min_value = serializers.FloatField(allow_null=True)
    max_value = serializers.FloatField(allow_null=True)


class CriteriaWrite(StrictFieldsMixin, serializers.Serializer):
    expected_updated_at = serializers.DateTimeField()
    expected_revision = serializers.CharField(max_length=64)
    criteria = CriterionWrite(many=True)

    def validate_criteria(self, rows):
        ids = [r["id"] for r in rows if r.get("id") is not None]
        if len(rows) > 100 or len(ids) != len(set(ids)):
            raise serializers.ValidationError(
                "Не больше 100 критериев, без повторяющихся ID."
            )
        return rows


def criteria_data(program):
    return {
        "updated_at": program.datetime_updated,
        "revision": revision(program),
        "locked": locked(program),
        # Historical scores have no timestamps; do not present the backfill date as first score.
        "supported_types": SUPPORTED_TYPES,
        "criteria": definitions(program),
    }


@transaction.atomic
def save_criteria(program_id, user, payload):
    program = managed_program(program_id, user, lock=True)
    if locked(program):
        raise CriteriaConflict(
            "criteria_locked",
            "В программе уже сохранена первая оценка. Критерии больше нельзя менять.",
        )
    serializer = CriteriaWrite(data=payload)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["expected_updated_at"] != program.datetime_updated or data[
        "expected_revision"
    ] != revision(program):
        raise CriteriaConflict(
            "stale_criteria", "Настройки изменены. Обновите действующие критерии."
        )
    existing = {c.pk: c for c in program.criterias.all()}
    keep = []
    for row in data["criteria"]:
        pk = row.pop("id", None)
        old = existing.get(pk)
        if pk is not None and old is None:
            raise serializers.ValidationError(
                {"criteria": "Критерий не принадлежит этой программе."}
            )
        unchanged = old and all(getattr(old, key) == value for key, value in row.items())
        if not unchanged:
            if row["type"] not in SUPPORTED_TYPES:
                raise serializers.ValidationError(
                    {"criteria": "Дробный критерий можно только сохранить без изменений."}
                )
            low, high = row["min_value"], row["max_value"]
            if row["type"] == "int":
                if (
                    any(
                        v is None or not math.isfinite(v) or not v.is_integer()
                        for v in (low, high)
                    )
                    or low > high
                ):
                    raise serializers.ValidationError(
                        {
                            "criteria": "Укажите целые минимум и максимум; максимум не меньше минимума."
                        }
                    )
            elif low is not None or high is not None:
                raise serializers.ValidationError(
                    {"criteria": "Шкала доступна только для баллов."}
                )
        if old:
            Criteria.objects.filter(pk=pk).update(**row)
            keep.append(pk)
        else:
            keep.append(Criteria.objects.create(partner_program=program, **row).pk)
    program.criterias.exclude(pk__in=keep).delete()
    program.evaluation_criteria_version += 1
    program.datetime_updated = timezone.now()
    PartnerProgram.objects.filter(pk=program.pk).update(
        evaluation_criteria_version=program.evaluation_criteria_version,
        datetime_updated=program.datetime_updated,
    )
    return criteria_data(program)

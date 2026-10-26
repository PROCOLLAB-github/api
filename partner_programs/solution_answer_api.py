import math

from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.solution_api import (
    CommandInteger,
    NameField,
    StrictSerializer,
    solution_data,
)
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_answers import update_solution


class AnswerValueField(serializers.Field):
    def to_internal_value(self, value):
        if isinstance(value, (str, bool)):
            return value
        if isinstance(value, (int, float)):
            try:
                if math.isfinite(value):
                    return value
            except OverflowError:
                pass
        if (
            isinstance(value, dict)
            and set(value) == {"url"}
            and isinstance(value["url"], str)
        ):
            return value
        raise serializers.ValidationError(
            "Ожидается текст, число, логическое значение или один файл."
        )

    def to_representation(self, value):
        return value


class AnswerPatchSerializer(StrictSerializer):
    field_id = CommandInteger(min_value=1, max_value=MAX_ID)
    value = AnswerValueField(allow_null=True)


class UpdateSolutionSerializer(StrictSerializer):
    expected_version = CommandInteger(min_value=1)
    expected_form_revision = serializers.RegexField(
        r"^[a-f0-9]{64}$", trim_whitespace=False
    )
    name = NameField(min_length=1, max_length=256, required=False, trim_whitespace=False)
    answers = AnswerPatchSerializer(many=True, required=False)

    def validate(self, data):
        if not ({"name", "answers"} & data.keys()):
            raise serializers.ValidationError(
                {"fields": "Укажите название или изменяемые ответы."}
            )
        return data


@transaction.atomic
def patch_solution(request, pk, solution_id):
    query = StrictSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    serializer = UpdateSolutionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    solution = update_solution(
        program_id=pk,
        solution_id=solution_id,
        actor=request.user,
        **serializer.validated_data
    )
    return Response(solution_data(solution, request.user))

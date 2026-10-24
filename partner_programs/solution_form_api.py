"""C00 API актуальной формы, безопасного конструктора и начальных шаблонов."""

import math

from rest_framework import serializers
from rest_framework.response import Response

from partner_programs import solution_forms
from partner_programs.solution_api import (
    CommandInteger,
    NameField,
    SolutionAPIView,
    StrictSerializer,
)
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_invitation_api import no_query
from partner_programs.solution_schema import (
    FIELD_TYPES,
    MAX_FILE_SIZE,
    PURPOSES,
    TEMPLATES,
    form_data,
    template_fields,
)
from partner_programs.solution_team import program_for


class CommandBoolean(serializers.BooleanField):
    def to_internal_value(self, value):
        if not isinstance(value, bool):
            self.fail("invalid")
        return value


class CommandNumber(serializers.Field):
    def to_internal_value(self, value):
        try:
            valid = (
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(value)
            )
        except OverflowError:
            valid = False
        if not valid:
            raise serializers.ValidationError("Ожидается конечное число.")
        return value

    def to_representation(self, value):
        return value


class ValidationSerializer(StrictSerializer):
    min_length = CommandInteger(min_value=0, allow_null=True)
    max_length = CommandInteger(min_value=0, allow_null=True)
    minimum = CommandNumber(allow_null=True)
    maximum = CommandNumber(allow_null=True)
    allowed_extensions = serializers.ListField(
        child=serializers.RegexField(r"^[a-z0-9]+$", trim_whitespace=False)
    )
    max_file_size_bytes = CommandInteger(
        min_value=1, max_value=MAX_FILE_SIZE, allow_null=True
    )


class FieldWriteSerializer(StrictSerializer):
    id = CommandInteger(min_value=1, max_value=MAX_ID, allow_null=True)
    type = serializers.ChoiceField(choices=FIELD_TYPES)
    purpose = serializers.ChoiceField(choices=PURPOSES)
    label = NameField(min_length=1, max_length=256, trim_whitespace=False)
    help_text = NameField(max_length=4000, allow_blank=True, trim_whitespace=False)
    required = CommandBoolean()
    position = CommandInteger(min_value=0)
    options = serializers.ListField(
        child=NameField(min_length=1, max_length=1000, trim_whitespace=False)
    )
    validation = ValidationSerializer()


class FormWriteSerializer(StrictSerializer):
    expected_revision = serializers.RegexField(r"^[a-f0-9]{64}$", trim_whitespace=False)
    template = serializers.ChoiceField(choices=TEMPLATES)
    fields = FieldWriteSerializer(many=True)


class SolutionFormView(SolutionAPIView):
    def get(self, request, pk):
        no_query(request)
        program = program_for(pk)
        solution_forms.require_reader(program, request.user)
        return Response(form_data(program))


class ManagedSolutionFormView(SolutionAPIView):
    def get(self, request, pk):
        no_query(request)
        program = program_for(pk)
        solution_forms.require_manager(program, request.user)
        return Response(solution_forms.management_data(program))

    def put(self, request, pk):
        no_query(request)
        serializer = FormWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            solution_forms.save_form(
                program_id=pk, actor=request.user, **serializer.validated_data
            )
        )


class SolutionFormTemplatesView(SolutionAPIView):
    def get(self, request):
        no_query(request)
        return Response(template_fields())

from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.solution_api import (
    CommandInteger,
    StrictSerializer,
    SolutionAPIView,
    solution_data,
)
from partner_programs.solution_submission import submit_solution


class SubmitSolutionSerializer(StrictSerializer):
    expected_version = CommandInteger(min_value=1)
    expected_form_revision = serializers.RegexField(
        r"^[a-f0-9]{64}$", trim_whitespace=False
    )


class SolutionSubmitView(SolutionAPIView):
    @transaction.atomic
    def post(self, request, pk, solution_id):
        query = StrictSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = SubmitSolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        solution = submit_solution(
            program_id=pk,
            solution_id=solution_id,
            actor=request.user,
            **serializer.validated_data
        )
        return Response(solution_data(solution, request.user))

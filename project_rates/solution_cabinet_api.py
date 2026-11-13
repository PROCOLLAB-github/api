import json

from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from partner_programs.solution_api import StrictSerializer
from partner_programs.solution_errors import MAX_ID
from partner_programs.serializers import ProgramProjectFilterRequestSerializer
from project_rates.solution_evaluation_api import EvaluationAPIView
from project_rates.solution_cabinet import cabinet_applications


class CabinetQuery(StrictSerializer):
    status = serializers.ChoiceField(choices=["pending", "completed"], default="pending")
    q = serializers.CharField(  # noqa: VNE001
        max_length=200, allow_blank=True, default=""
    )
    program_id = serializers.IntegerField(min_value=1, max_value=MAX_ID, required=False)
    filters = serializers.CharField(max_length=4000, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)

    def validate_filters(self, value):
        try:
            filters = json.loads(value)
        except ValueError as exc:
            raise serializers.ValidationError("Не удалось прочитать фильтры.") from exc
        validator = ProgramProjectFilterRequestSerializer(data={"filters": filters})
        validator.is_valid(raise_exception=True)
        return validator.validated_data["filters"]

    def validate(self, attrs):
        if attrs.get("filters") and not attrs.get("program_id"):
            raise serializers.ValidationError("Выберите программу для фильтрации.")
        return attrs


class CabinetApplicationsView(EvaluationAPIView):
    # The shared cabinet also serves project programs when solutions are disabled.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = CabinetQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(cabinet_applications(request.user, query.validated_data))

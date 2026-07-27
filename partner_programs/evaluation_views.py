# Roadmap: DEV-050, DEV-051, DEV-052
# Контур экспертного доступа к Submission и управления Evaluation.

from drf_yasg import openapi
from drf_yasg.utils import no_body, swagger_auto_schema
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.throttling import PostOnlyScopedRateThrottle
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.permissions import IsAdminOrManagerOfProgram
from partner_programs.serializers.evaluations import (
    EvaluationDraftCreateSerializer,
    EvaluationDraftUpdateSerializer,
    EvaluationReadSerializer,
    ExpertSubmissionDetailSerializer,
    ExpertSubmissionFilterSerializer,
    ExpertSubmissionListSerializer,
    ManagerEvaluationFilterSerializer,
    ManagerEvaluationSerializer,
)
from partner_programs.services.evaluations import (
    EvaluationAccessDeniedError,
    EvaluationConflictError,
    EvaluationNotFoundError,
    EvaluationServiceError,
    EvaluationValidationError,
    create_or_get_draft_evaluation,
    expert_submission_assignments,
    get_expert_submission_detail,
    get_my_evaluation,
    get_visible_evaluation,
    manager_evaluations_queryset,
    submit_evaluation,
    update_draft_evaluation,
)
from partner_programs.submission_assignment_views import ProgramPermissionMixin
from partner_programs.throttling import PatchOnlyScopedRateThrottle


PROGRAM_ID_PARAMETER = openapi.Parameter(
    "program_id",
    openapi.IN_QUERY,
    description="Фильтр по идентификатору программы.",
    type=openapi.TYPE_INTEGER,
)
SUBMISSION_STATUS_PARAMETER = openapi.Parameter(
    "submission_status",
    openapi.IN_QUERY,
    description="Фильтр по статусу Submission.",
    type=openapi.TYPE_STRING,
)
EVALUATION_STATUS_PARAMETER = openapi.Parameter(
    "evaluation_status",
    openapi.IN_QUERY,
    description="Фильтр по статусу Evaluation: draft, submitted или none.",
    type=openapi.TYPE_STRING,
)
SUBMISSION_ID_PARAMETER = openapi.Parameter(
    "submission_id",
    openapi.IN_QUERY,
    description="Фильтр по идентификатору Submission.",
    type=openapi.TYPE_INTEGER,
)
EXPERT_ID_PARAMETER = openapi.Parameter(
    "expert_id",
    openapi.IN_QUERY,
    description="Фильтр по идентификатору Expert.",
    type=openapi.TYPE_INTEGER,
)
ASSIGNMENT_STATUS_PARAMETER = openapi.Parameter(
    "assignment_status",
    openapi.IN_QUERY,
    description="Фильтр по статусу назначения.",
    type=openapi.TYPE_STRING,
)
STAGE_KEY_PARAMETER = openapi.Parameter(
    "stage_key",
    openapi.IN_QUERY,
    description="Фильтр по этапу Submission.",
    type=openapi.TYPE_STRING,
)


def _domain_error_response(exc):
    if isinstance(exc, EvaluationAccessDeniedError):
        raise PermissionDenied(exc.detail, code=exc.code) from exc
    if isinstance(exc, EvaluationNotFoundError):
        raise NotFound(exc.detail, code=exc.code) from exc
    if isinstance(exc, EvaluationValidationError):
        return Response(
            {exc.field or "detail": [exc.detail]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, EvaluationConflictError):
        return Response(
            {"detail": exc.detail, "code": exc.code},
            status=status.HTTP_409_CONFLICT,
        )
    raise exc


class ExpertSubmissionListView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = PartnerProgramPagination

    @swagger_auto_schema(
        operation_description=(
            "PII-safe список Submission, назначенных текущему эксперту. "
            "Роль Expert без назначения не даёт доступ к решению."
        ),
        manual_parameters=[
            PROGRAM_ID_PARAMETER,
            SUBMISSION_STATUS_PARAMETER,
            EVALUATION_STATUS_PARAMETER,
        ],
        responses={
            200: ExpertSubmissionListSerializer(many=True),
            400: "Некорректный фильтр.",
            401: "Требуется авторизация.",
            403: "У пользователя нет профиля Expert.",
        },
    )
    def get(self, request):
        filter_serializer = ExpertSubmissionFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        try:
            queryset = expert_submission_assignments(user=request.user)
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)

        filters = filter_serializer.validated_data
        if "program_id" in filters:
            queryset = queryset.filter(submission__program_id=filters["program_id"])
        if "submission_status" in filters:
            queryset = queryset.filter(submission__status=filters["submission_status"])
        if "evaluation_status" in filters:
            evaluation_status = filters["evaluation_status"]
            if evaluation_status == "none":
                queryset = queryset.filter(my_evaluation_id__isnull=True)
            else:
                queryset = queryset.filter(my_evaluation_status=evaluation_status)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            ExpertSubmissionListSerializer(page, many=True).data
        )


class ExpertSubmissionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description=(
            "PII-safe detail назначенной Submission. form_data участника "
            "намеренно не включается; возвращаются description и отдельные links."
        ),
        responses={
            200: ExpertSubmissionDetailSerializer,
            401: "Требуется авторизация.",
            404: "Submission не назначена текущему эксперту.",
        },
    )
    def get(self, request, submission_id):
        try:
            result = get_expert_submission_detail(
                submission_id=submission_id,
                user=request.user,
            )
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)
        return Response(ExpertSubmissionDetailSerializer(result).data)


class MyEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description=(
            "Возвращает существующую Evaluation текущего назначенного эксперта. "
            "GET никогда не создаёт черновик."
        ),
        responses={
            200: EvaluationReadSerializer,
            401: "Требуется авторизация.",
            404: "Evaluation не существует или Submission не назначена.",
        },
    )
    def get(self, request, submission_id):
        try:
            evaluation = get_my_evaluation(
                submission_id=submission_id,
                user=request.user,
            )
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)
        return Response(EvaluationReadSerializer(evaluation).data)


class EvaluationCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "evaluation_create"

    @swagger_auto_schema(
        operation_description=(
            "Создаёт draft Evaluation для assigned-назначения. Первый запрос "
            "возвращает 201; повторный POST возвращает тот же draft с 200 и "
            "не изменяет его. Для submitted Evaluation возвращается 409."
        ),
        request_body=EvaluationDraftCreateSerializer,
        responses={
            200: EvaluationReadSerializer,
            201: EvaluationReadSerializer,
            400: "Некорректные Criteria или значения.",
            401: "Требуется авторизация.",
            404: "Submission не назначена.",
            409: "Конфликт статуса назначения, Submission или Evaluation.",
            429: "Превышен evaluation_create throttle.",
        },
    )
    def post(self, request, submission_id):
        serializer = EvaluationDraftCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = create_or_get_draft_evaluation(
                submission_id=submission_id,
                user=request.user,
                comment=serializer.validated_data["comment"],
                scores=serializer.validated_data["scores"],
            )
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)
        response_status = (
            status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        )
        return Response(
            EvaluationReadSerializer(result.evaluation).data,
            status=response_status,
        )


class EvaluationDetailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PatchOnlyScopedRateThrottle]
    throttle_scope = "evaluation_update"

    @swagger_auto_schema(
        operation_description=(
            "Read-only detail для владельца-эксперта, manager программы и staff."
        ),
        responses={
            200: EvaluationReadSerializer,
            401: "Требуется авторизация.",
            404: "Evaluation скрыта или не существует.",
        },
    )
    def get(self, request, evaluation_id):
        try:
            evaluation = get_visible_evaluation(
                evaluation_id=evaluation_id,
                user=request.user,
            )
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)
        return Response(EvaluationReadSerializer(evaluation).data)

    @swagger_auto_schema(
        operation_description=(
            "Autosave draft Evaluation владельцем. Если scores передан, набор "
            "заменяется целиком в одной транзакции. Submitted Evaluation "
            "неизменяема."
        ),
        request_body=EvaluationDraftUpdateSerializer,
        responses={
            200: EvaluationReadSerializer,
            400: "Некорректные Criteria или значения.",
            401: "Требуется авторизация.",
            404: "Чужая или скрытая Evaluation.",
            409: "Evaluation или assignment недоступны для изменения.",
            429: "Превышен evaluation_update throttle.",
        },
    )
    def patch(self, request, evaluation_id):
        serializer = EvaluationDraftUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            evaluation = update_draft_evaluation(
                evaluation_id=evaluation_id,
                user=request.user,
                comment_supplied="comment" in serializer.validated_data,
                comment=serializer.validated_data.get("comment", ""),
                scores_supplied="scores" in serializer.validated_data,
                scores=serializer.validated_data.get("scores"),
            )
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)
        return Response(EvaluationReadSerializer(evaluation).data)


class EvaluationSubmitView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PostOnlyScopedRateThrottle]
    throttle_scope = "evaluation_submit"

    @swagger_auto_schema(
        operation_description=(
            "Атомарно отправляет полную Evaluation и завершает assignment. "
            "Повторный submit идемпотентен и не меняет submitted_at."
        ),
        request_body=no_body,
        responses={
            200: EvaluationReadSerializer,
            400: "Заполнены не все Criteria или значения невалидны.",
            401: "Требуется авторизация.",
            404: "Чужая или скрытая Evaluation.",
            409: "Assignment или Submission недоступны.",
            429: "Превышен evaluation_submit throttle.",
        },
    )
    def post(self, request, evaluation_id):
        try:
            evaluation = submit_evaluation(
                evaluation_id=evaluation_id,
                user=request.user,
            )
        except EvaluationServiceError as exc:
            return _domain_error_response(exc)
        return Response(EvaluationReadSerializer(evaluation).data)


class ProgramEvaluationListView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    pagination_class = PartnerProgramPagination

    @swagger_auto_schema(
        operation_description=(
            "Read-only список Evaluation указанной программы для manager и staff."
        ),
        manual_parameters=[
            SUBMISSION_ID_PARAMETER,
            EXPERT_ID_PARAMETER,
            EVALUATION_STATUS_PARAMETER,
            ASSIGNMENT_STATUS_PARAMETER,
            STAGE_KEY_PARAMETER,
        ],
        responses={
            200: ManagerEvaluationSerializer(many=True),
            400: "Некорректный фильтр.",
            401: "Требуется авторизация.",
            403: "Нет прав manager этой программы.",
            404: "Программа не найдена.",
        },
    )
    def get(self, request, program_id):
        serializer = ManagerEvaluationFilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        queryset = manager_evaluations_queryset(program=self.program)
        filters = serializer.validated_data
        if "submission_id" in filters:
            queryset = queryset.filter(submission_id=filters["submission_id"])
        if "expert_id" in filters:
            queryset = queryset.filter(expert_id=filters["expert_id"])
        if "evaluation_status" in filters:
            queryset = queryset.filter(status=filters["evaluation_status"])
        if "assignment_status" in filters:
            queryset = queryset.filter(assignment_status=filters["assignment_status"])
        if "stage_key" in filters:
            queryset = queryset.filter(submission__stage_key=filters["stage_key"])

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            ManagerEvaluationSerializer(page, many=True).data
        )


class ProgramEvaluationDetailView(ProgramPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    @swagger_auto_schema(
        operation_description=(
            "Read-only Evaluation detail для manager указанной программы и staff."
        ),
        responses={
            200: ManagerEvaluationSerializer,
            401: "Требуется авторизация.",
            403: "Нет прав manager этой программы.",
            404: "Программа или Evaluation не найдена.",
        },
    )
    def get(self, request, program_id, evaluation_id):
        evaluation = get_object_or_404(
            manager_evaluations_queryset(program=self.program),
            pk=evaluation_id,
        )
        return Response(ManagerEvaluationSerializer(evaluation).data)

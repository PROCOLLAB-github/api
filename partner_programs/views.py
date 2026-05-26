import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.timezone import now
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from openpyxl import Workbook
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.serializers import EmptySerializer, SetLikedSerializer, SetViewedSerializer
from core.services import add_view, set_like
from core.utils import (
    XlsxFileToExport,
    build_xlsx_download_response,
    sanitize_excel_value,
)
from moderation.services import (
    ModerationTransitionError,
    submit_program_to_moderation,
    withdraw_program_from_moderation,
)
from partner_programs.analytics import (
    build_program_analytics_payload,
    build_program_analytics_xlsx,
)
from partner_programs.helpers import date_to_iso
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramInvite,
    PartnerProgramLegalSettings,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.permissions import (
    IsAdminOrManagerOfProgram,
    IsProjectLeader,
)
from partner_programs.serializers import (
    CompanyBriefSerializer,
    LegalDocumentSerializer,
    PartnerProgramCreateSerializer,
    PartnerProgramDataSchemaSerializer,
    PartnerProgramFieldSerializer,
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
    PartnerProgramInviteCreateSerializer,
    PartnerProgramInviteSerializer,
    PartnerProgramLegalSettingsSerializer,
    PartnerProgramListSerializer,
    PartnerProgramNewUserSerializer,
    PartnerProgramProjectApplySerializer,
    PartnerProgramUpdateSerializer,
    PartnerProgramUserSerializer,
    PartnerProgramVerificationStatusSerializer,
    PartnerProgramVerificationSubmitSerializer,
    ProgramProjectFilterRequestSerializer,
    PublicPartnerProgramInviteSerializer,
)
from partner_programs.privacy import (
    accept_organizer_terms,
    active_legal_documents_by_type,
    can_view_participant_contacts,
    create_participant_consent,
    log_personal_data_access,
    strip_registration_consent_keys,
)
from partner_programs.services import (
    BASE_COLUMNS,
    ProgramInviteError,
    ProgramInviteGoneError,
    ProgramInviteNotFoundError,
    accept_program_invite,
    build_program_field_columns,
    create_program_invites,
    get_active_program_invite,
    get_moderation_submission_errors,
    get_program_readiness_payload,
    prepare_project_scores_export_data,
    resend_program_invite,
    revoke_program_invite,
    row_dict_for_link,
    validate_project_team_size_for_program,
)
from partner_programs.utils import filter_program_projects_by_field_name
from partner_programs.verification_services import (
    VerificationTransitionError,
    submit_verification_request,
)
from projects.models import Collaborator, Company, Project
from partner_programs.serializers import PartnerProgramFieldValueUpdateSerializer
from projects.serializers import ProjectListSerializer
from vacancy.mapping import MessageTypeEnum, UserProgramRegisterParams
from vacancy.tasks import send_email

User = get_user_model()


class CompanySearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = (request.query_params.get("query") or "").strip()
        qs = Company.objects.all()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(inn__icontains=query))
        return Response(
            CompanyBriefSerializer(qs.order_by("name", "id")[:20], many=True).data,
            status=status.HTTP_200_OK,
        )


class ActiveLegalDocumentsView(generics.ListAPIView):
    serializer_class = LegalDocumentSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return list(active_legal_documents_by_type().values())


def user_can_access_private_program(user, program: PartnerProgram) -> bool:
    if not user or not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    if program.is_manager(user):
        return True
    if PartnerProgramUserProfile.objects.filter(
        partner_program=program,
        user=user,
    ).exists():
        return True
    if program.experts.filter(user=user).exists():
        return True
    return False


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.select_related("company").filter(
        Q(status=PartnerProgram.STATUS_PUBLISHED)
        | Q(draft=False, status=PartnerProgram.STATUS_DRAFT)
    )
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PartnerProgramPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PartnerProgramCreateSerializer
        return self.serializer_class

    def get_queryset(self):
        user = self.request.user
        my_flag = self.request.query_params.get("my", "").lower() in {
            "1",
            "true",
            "yes",
        }
        if my_flag:
            if not user.is_authenticated:
                return PartnerProgram.objects.none()
            manager_qs = PartnerProgram.objects.filter(managers=user)
            member_qs = PartnerProgram.objects.filter(partner_program_profiles__user=user)
            expert_qs = PartnerProgram.objects.filter(experts__user=user)
            base_qs = (
                (manager_qs | member_qs | expert_qs)
                .select_related("company")
                .exclude(status=PartnerProgram.STATUS_ARCHIVED)
                .distinct()
            )
        else:
            base_qs = super().get_queryset()
        participating_flag = self.request.query_params.get("participating")
        if not participating_flag:
            if not user.is_authenticated:
                qs = base_qs.filter(is_private=False)
            elif getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
                qs = base_qs
            else:
                qs = (
                    base_qs.filter(is_private=False)
                    | base_qs.filter(
                        Q(partner_program_profiles__user=user)
                        | Q(managers=user)
                        | Q(experts__user=user)
                    )
                ).distinct()
        elif not self.request.user.is_authenticated:
            qs = PartnerProgram.objects.none()
        else:
            now = timezone.now()
            qs = base_qs.filter(
                partner_program_profiles__user=self.request.user,
                datetime_finished__gte=now,
            ).distinct()

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        verified_only = self.request.query_params.get("verified_only", "").lower()
        if verified_only in {"1", "true", "yes"}:
            qs = qs.filter(
                verification_status=PartnerProgram.VERIFICATION_STATUS_VERIFIED
            )

        user = self.request.user
        if not user.is_authenticated:
            return qs

        member_qs = PartnerProgramUserProfile.objects.filter(
            partner_program=OuterRef("pk"),
            user=user,
        )
        return qs.annotate(is_user_member=Exists(member_qs))


class PartnerProgramDetail(generics.RetrieveUpdateAPIView):
    queryset = (
        PartnerProgram.objects.select_related("company")
        .prefetch_related(
            "materials",
            "managers",
            "courses",
        )
        .all()
    )
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = PartnerProgramForUnregisteredUserSerializer

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return PartnerProgramUpdateSerializer
        return self.serializer_class

    def get(self, request, *args, **kwargs):
        program = self.get_object()
        if program.is_private and not user_can_access_private_program(
            request.user, program
        ):
            raise NotFound("Чемпионат доступен только по приглашению.")
        is_user_member = program.users.filter(pk=request.user.pk).exists()
        can_manage = self._has_edit_access(request.user, program)
        serializer_class = (
            PartnerProgramForMemberSerializer
            if is_user_member or can_manage
            else PartnerProgramForUnregisteredUserSerializer
        )
        serializer = serializer_class(
            program, context={"request": request, "user": request.user}
        )
        data = serializer.data
        data["is_user_member"] = is_user_member
        data["is_user_expert"] = (
            program.experts.filter(user=request.user).exists()
            if request.user.is_authenticated
            else False
        )
        data["status"] = program.status
        data["frozen_at"] = program.frozen_at
        data["is_frozen"] = program.status == PartnerProgram.STATUS_FROZEN
        if request.user.is_authenticated:
            add_view(program, request.user)
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, *args, **kwargs):
        program = self.get_object()
        if not self._has_edit_access(request.user, program):
            return Response(
                {"detail": "Not enough rights to edit this championship."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if program.status in (
            PartnerProgram.STATUS_PENDING_MODERATION,
            PartnerProgram.STATUS_FROZEN,
            PartnerProgram.STATUS_ARCHIVED,
        ):
            return Response(
                {"detail": "Championship is read-only in the current status."},
                status=status.HTTP_409_CONFLICT,
            )

        if program.status == PartnerProgram.STATUS_PUBLISHED:
            conflict = self._published_edit_conflict(program, request.data)
            if conflict:
                return Response({"detail": conflict}, status=status.HTTP_409_CONFLICT)

        old_schema = program.data_schema if "data_schema" in request.data else None
        response = self.partial_update(request, *args, **kwargs)
        if old_schema is not None and response.status_code < 400:
            program.refresh_from_db(fields=["data_schema"])
            self._log_registration_schema_changes(
                request.user,
                program,
                old_schema,
                program.data_schema,
                request,
            )
        return response

    def put(self, request, *args, **kwargs):
        return self.patch(request, *args, **kwargs)

    def _has_edit_access(self, user, program: PartnerProgram) -> bool:
        return bool(
            user
            and user.is_authenticated
            and (
                getattr(user, "is_staff", False)
                or getattr(user, "is_superuser", False)
                or program.is_manager(user)
            )
        )

    def _log_registration_schema_changes(self, actor, program, old_schema, new_schema, request):
        old_keys = set(old_schema.keys()) if isinstance(old_schema, dict) else set()
        new_keys = set(new_schema.keys()) if isinstance(new_schema, dict) else set()
        changes = [
            ("registration_form_field_created", sorted(new_keys - old_keys)),
            ("registration_form_field_deleted", sorted(old_keys - new_keys)),
            ("registration_form_field_updated", sorted(old_keys & new_keys)),
        ]
        for action, field_names in changes:
            if not field_names:
                continue
            log_personal_data_access(
                actor=actor,
                program=program,
                action=action,
                object_type="registration_form",
                object_id=program.id,
                metadata={
                    "field_names": field_names,
                    "request_path": request.path,
                },
            )

    def _published_edit_conflict(self, program: PartnerProgram, data) -> str | None:
        requested_fields = set(data.keys())
        public_fields = {
            "name",
            "description",
            "city",
            "cover_image_address",
            "mobile_cover_image_address",
            "image_address",
            "advertisement_image_address",
        }
        registration_fields = {"data_schema", "registration_link", "is_private"}
        participation_fields = {
            "participation_format",
            "project_team_min_size",
            "project_team_max_size",
        }

        if requested_fields & public_fields:
            return "Public fields may require a new moderation cycle after publication."

        has_participants = program.partner_program_profiles.exists()
        has_projects = program.program_projects.exists()
        has_submitted_projects = program.program_projects.filter(submitted=True).exists()

        if has_participants and requested_fields & registration_fields:
            return "Registration settings cannot be changed after participants joined."

        if (has_participants or has_projects) and requested_fields & participation_fields:
            return "Team participation rules cannot be changed after activity starts."

        if (
            has_submitted_projects
            and "is_competitive" in requested_fields
            and data.get("is_competitive") is False
        ):
            return "Competitive mode cannot be disabled after submitted projects exist."

        return None


class PartnerProgramStatsAPIView(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get(self, request, pk: int):
        program = get_object_or_404(PartnerProgram, pk=pk)
        if program.is_private and not user_can_access_private_program(
            request.user, program
        ):
            raise NotFound("Р§РµРјРїРёРѕРЅР°С‚ РґРѕСЃС‚СѓРїРµРЅ С‚РѕР»СЊРєРѕ РїРѕ РїСЂРёРіР»Р°С€РµРЅРёСЋ.")

        week_ago = timezone.now() - timedelta(days=7)
        participant_stats = PartnerProgramUserProfile.objects.filter(
            partner_program=program
        ).aggregate(
            participants_count=Count("id"),
            participants_delta_week=Count(
                "id",
                filter=Q(datetime_created__gte=week_ago),
            ),
        )
        project_stats = PartnerProgramProject.objects.filter(
            partner_program=program
        ).aggregate(
            projects_count=Count("id"),
            active_projects_count=Count("id", filter=Q(submitted=True)),
        )

        return Response(
            {
                **participant_stats,
                **project_stats,
                "experts_count": program.experts.count(),
                "experts_remaining_count": 0,
                "current_period": self._current_period(program),
            },
            status=status.HTTP_200_OK,
        )

    def _current_period(self, program: PartnerProgram) -> str:
        current_time = timezone.now()
        submission_deadline = program.get_project_submission_deadline()

        if program.datetime_started and current_time < program.datetime_started:
            return "not_started"
        if (
            program.datetime_registration_ends
            and current_time <= program.datetime_registration_ends
        ):
            return "registration"
        if submission_deadline and current_time <= submission_deadline:
            return "project_submission"
        if (
            program.datetime_evaluation_ends
            and current_time <= program.datetime_evaluation_ends
        ):
            return "evaluation"
        if program.datetime_finished and current_time <= program.datetime_finished:
            return "running"
        return "finished"


class PartnerProgramVerificationStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        payload = PartnerProgramVerificationStatusSerializer.build_payload(
            program,
            user=request.user,
        )
        return Response(
            PartnerProgramVerificationStatusSerializer(payload).data,
            status=status.HTTP_200_OK,
        )


class PartnerProgramVerificationSubmitView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def post(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        serializer = PartnerProgramVerificationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            submit_verification_request(
                program=program,
                author=request.user,
                **data,
            )
        except VerificationTransitionError as exc:
            return Response(
                {
                    "detail": "Заявка уже находится на рассмотрении"
                    if exc.current_status == PartnerProgram.VERIFICATION_STATUS_PENDING
                    else "Компания уже подтверждена",
                    "current_status": exc.current_status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        program.refresh_from_db()
        payload = PartnerProgramVerificationStatusSerializer.build_payload(
            program,
            user=request.user,
        )
        return Response(
            PartnerProgramVerificationStatusSerializer(payload).data,
            status=status.HTTP_201_CREATED,
        )


class PartnerProgramInviteListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        qs = PartnerProgramInvite.objects.filter(program=program).select_related(
            "accepted_by",
            "created_by",
        )
        invite_status = request.query_params.get("status")
        if invite_status:
            qs = qs.filter(status=invite_status)
        return Response(PartnerProgramInviteSerializer(qs, many=True).data)

    def post(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        serializer = PartnerProgramInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            invites = create_program_invites(
                program=program,
                emails=serializer.validated_data["emails"],
                created_by=request.user,
                expires_in_days=serializer.validated_data["expires_in_days"],
                custom_message=serializer.validated_data.get("custom_message", ""),
            )
        except ProgramInviteError as exc:
            return Response(
                {"detail": str(exc)},
                status=getattr(exc, "status_code", status.HTTP_400_BAD_REQUEST),
            )

        return Response(
            PartnerProgramInviteSerializer(invites, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class PartnerProgramInviteRevokeView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def post(self, request, pk, invite_id):
        invite = get_object_or_404(PartnerProgramInvite, pk=invite_id, program_id=pk)
        try:
            revoke_program_invite(invite)
        except ProgramInviteGoneError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_410_GONE)
        return Response(PartnerProgramInviteSerializer(invite).data)


class PartnerProgramInviteResendView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def post(self, request, pk, invite_id):
        invite = get_object_or_404(
            PartnerProgramInvite.objects.select_related("program__company"),
            pk=invite_id,
            program_id=pk,
        )
        serializer = PartnerProgramInviteCreateSerializer(
            data={
                "email": invite.email,
                "expires_in_days": request.data.get("expires_in_days", 30),
                "custom_message": request.data.get("custom_message", ""),
            }
        )
        serializer.is_valid(raise_exception=True)
        try:
            resend_program_invite(
                invite,
                expires_in_days=serializer.validated_data["expires_in_days"],
                custom_message=serializer.validated_data.get("custom_message", ""),
            )
        except ProgramInviteGoneError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_410_GONE)
        return Response(PartnerProgramInviteSerializer(invite).data)


class PartnerProgramInviteDeleteView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def delete(self, request, pk, invite_id):
        invite = get_object_or_404(PartnerProgramInvite, pk=invite_id, program_id=pk)
        if invite.status not in (
            PartnerProgramInvite.STATUS_EXPIRED,
            PartnerProgramInvite.STATUS_REVOKED,
        ):
            return Response(
                {"detail": "Удалить можно только отозванное или истекшее приглашение."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicPartnerProgramInviteView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            invite = get_active_program_invite(token)
        except ProgramInviteNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ProgramInviteGoneError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "status": exc.invite.status,
                },
                status=status.HTTP_410_GONE,
            )
        return Response(PublicPartnerProgramInviteSerializer(invite).data)


class PublicPartnerProgramInviteAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        try:
            invite = accept_program_invite(token=token, user=request.user)
        except ProgramInviteNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ProgramInviteGoneError as exc:
            return Response(
                {
                    "detail": str(exc),
                    "status": exc.invite.status,
                },
                status=status.HTTP_410_GONE,
            )
        return Response(
            {
                "program_id": invite.program_id,
                "invite_id": invite.id,
                "status": invite.status,
            },
            status=status.HTTP_200_OK,
        )


class PublicPartnerProgramInvitePageView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            invite = get_active_program_invite(token)
            response_status = status.HTTP_200_OK
            context = {
                "is_valid": True,
                "invite": PublicPartnerProgramInviteSerializer(invite).data,
            }
        except ProgramInviteNotFoundError as exc:
            response_status = status.HTTP_404_NOT_FOUND
            context = {"is_valid": False, "message": str(exc)}
        except ProgramInviteGoneError as exc:
            response_status = status.HTTP_410_GONE
            context = {
                "is_valid": False,
                "message": str(exc),
                "invite_status": exc.invite.status,
            }
        return render(
            request,
            "partner_programs/invite.html",
            context,
            status=response_status,
        )


class PartnerProgramReadinessView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        if not self._has_access(request.user, program):
            raise PermissionDenied("Readiness is available only to program managers.")

        program.readiness = program.calculate_readiness()
        program.save(update_fields=["readiness", "datetime_updated"])
        return Response(get_program_readiness_payload(program), status=status.HTTP_200_OK)

    def _has_access(self, user, program: PartnerProgram) -> bool:
        return bool(
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or program.is_manager(user)
        )


class PartnerProgramLegalSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        settings_obj, _ = PartnerProgramLegalSettings.objects.get_or_create(
            program=program
        )
        return Response(
            PartnerProgramLegalSettingsSerializer(settings_obj).data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        settings_obj, _ = PartnerProgramLegalSettings.objects.get_or_create(
            program=program
        )
        serializer = PartnerProgramLegalSettingsSerializer(
            settings_obj,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class PartnerProgramAcceptOrganizerTermsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def post(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        settings_obj = accept_organizer_terms(program=program, user=request.user)
        return Response(
            PartnerProgramLegalSettingsSerializer(settings_obj).data,
            status=status.HTTP_200_OK,
        )


class PartnerProgramSubmitToModerationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        if not self._has_access(request.user, program):
            raise PermissionDenied("Only program managers can submit to moderation.")

        if program.status not in (
            PartnerProgram.STATUS_DRAFT,
            PartnerProgram.STATUS_REJECTED,
        ):
            return Response(
                {
                    "detail": (
                        "Невозможно отправить на модерацию из статуса "
                        f"{program.status}"
                    ),
                    "current_status": program.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        errors = get_moderation_submission_errors(program)
        readiness = get_program_readiness_payload(program)
        if errors:
            return Response(
                {
                    "detail": "Чемпионат не может быть отправлен на модерацию",
                    "errors": errors,
                    "privacy_blockers": readiness["privacy_blockers"],
                    "current_status": program.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        log = submit_program_to_moderation(program, author=request.user)
        program.readiness = program.calculate_readiness()
        program.save(update_fields=["readiness", "datetime_updated"])
        return Response(
            {
                "id": program.id,
                "status": program.status,
                "submitted_at": log.datetime_created.isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    def _has_access(self, user, program: PartnerProgram) -> bool:
        return bool(
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or program.is_manager(user)
        )


class PartnerProgramWithdrawFromModerationView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def post(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        try:
            log = withdraw_program_from_moderation(program, author=request.user)
        except ModerationTransitionError as exc:
            return Response(
                {
                    "detail": (
                        "Невозможно отозвать чемпионат с модерации из статуса "
                        f"{exc.current_status}"
                    ),
                    "current_status": exc.current_status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        program.readiness = program.calculate_readiness()
        program.save(update_fields=["readiness", "datetime_updated"])
        return Response(
            {
                "id": program.id,
                "status": program.status,
                "withdrawn_at": log.datetime_created.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


class PartnerProgramProjectApplyView(GenericAPIView):
    """
    Создание проекта в рамках программы (подать проект).
    Проект создаётся как непубличный черновик.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramProjectApplySerializer
    queryset = PartnerProgram.objects.all()

    def _require_can_apply(self, program: PartnerProgram, user: User):
        if not program.is_project_submission_open():
            raise ValidationError("Срок подачи проектов в программу завершён.")

        if program.is_manager(user):
            return

        if not PartnerProgramUserProfile.objects.filter(
            user=user, partner_program=program
        ).exists():
            raise PermissionDenied("Подача проекта доступна только участникам программы.")

    def get(self, request, pk, *args, **kwargs):
        program = self.get_object()
        self._require_can_apply(program, request.user)

        fields_qs = program.fields.all()
        return Response(
            {
                "program_id": program.id,
                "can_submit": program.is_project_submission_open(),
                "submission_deadline": program.get_project_submission_deadline(),
                "program_fields": PartnerProgramFieldSerializer(
                    fields_qs, many=True
                ).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, pk, *args, **kwargs):
        program = self.get_object()
        self._require_can_apply(program, request.user)

        existing_link = (
            PartnerProgramProject.objects.select_related("project")
            .filter(partner_program=program, project__leader=request.user)
            .first()
        )
        if existing_link:
            return Response(
                {
                    "detail": "Проект уже подан в эту программу.",
                    "project_id": existing_link.project_id,
                    "program_link_id": existing_link.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        project_data = data.get("project")
        project_id = data.get("project_id")
        values_data = data.get("program_field_values") or []

        seen_field_ids: set[int] = set()
        duplicate_ids: set[int] = set()
        for item in values_data:
            field_id = item["field"].id
            if field_id in seen_field_ids:
                duplicate_ids.add(field_id)
            seen_field_ids.add(field_id)
        if duplicate_ids:
            raise ValidationError(
                {
                    "program_field_values": f"Есть повторяющиеся field_id: {sorted(duplicate_ids)}"
                }
            )

        required_fields = list(
            program.fields.filter(is_required=True).values("id", "label")
        )
        provided_field_ids = {item["field"].id for item in values_data}
        missing_required = [
            f["label"] for f in required_fields if f["id"] not in provided_field_ids
        ]
        if missing_required:
            raise ValidationError(
                {
                    "program_field_values": f"Не заполнены обязательные поля: {missing_required}"
                }
            )

        with transaction.atomic():
            if project_id is not None:
                project = get_object_or_404(Project, pk=project_id)
                if project.leader_id != request.user.id:
                    raise PermissionDenied(
                        "Only project leader can link project to program."
                    )

                existing_program_link = (
                    project.program_links.select_related("partner_program")
                    .exclude(partner_program=program)
                    .first()
                )
                if existing_program_link:
                    raise ValidationError(
                        {"project_id": "Project is already linked to another program."}
                    )

                program_link, _ = PartnerProgramProject.objects.get_or_create(
                    partner_program=program, project=project
                )
            else:
                project = Project.objects.create(
                    leader=request.user,
                    draft=True,
                    is_public=False,
                    **project_data,
                )
                program_link = PartnerProgramProject.objects.create(
                    partner_program=program, project=project
                )

            profile = PartnerProgramUserProfile.objects.filter(
                user=request.user, partner_program=program
            ).first()
            if profile:
                profile.project = project
                profile.save(update_fields=["project"])

            value_objs: list[PartnerProgramFieldValue] = []
            for item in values_data:
                field = item["field"]
                if field.partner_program_id != program.id:
                    raise ValidationError(
                        {
                            "program_field_values": f"Поле id={field.id} не относится к этой программе."
                        }
                    )
                value_objs.append(
                    PartnerProgramFieldValue(
                        program_project=program_link,
                        field=field,
                        value_text=item.get("value_text") or "",
                    )
                )

            if value_objs:
                PartnerProgramFieldValue.objects.bulk_create(value_objs)

        return Response(
            {
                "project_id": project.id,
                "program_link_id": program_link.id,
            },
            status=status.HTTP_201_CREATED,
        )


class PartnerProgramCreateUserAndRegister(generics.GenericAPIView):
    """
    Create new user and register him to program and save additional data.
    If a user with such an email already exists in the system, then his profile
    remains the same, but he registers in the program with the specified data.
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramNewUserSerializer
    queryset = PartnerProgram.objects.all()

    def post(self, request, *args, **kwargs):
        data = request.data
        # tilda cringe
        if data.get("test") == "test":
            return Response(status=status.HTTP_200_OK)

        try:
            program = self.get_object()
        except PartnerProgram.DoesNotExist:
            return Response({"asd": "asd"}, status=status.HTTP_404_NOT_FOUND)

        if program.status != PartnerProgram.STATUS_PUBLISHED:
            return Response(
                data={
                    "detail": "Registration for this program is not available.",
                    "current_status": program.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        if program.is_private:
            return Response(
                data={"detail": "Registration for this program is invite-only."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # tilda cringe
        email = data.get("email") if data.get("email") else data.get("email_")
        if not email:
            return Response(
                data={"detail": "You need to pass an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        password = data.get("password")
        if not password:
            return Response(
                data={"detail": "You need to pass a password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_fields = (
            "first_name",
            "last_name",
            "patronymic",
            "city",
        )
        try:
            with transaction.atomic():
                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "birthday": date_to_iso(data.get("birthday", "01-01-1900")),
                        "is_active": True,  # bypass email verification
                        "onboarding_stage": None,  # bypass onboarding
                        "verification_date": timezone.now(),  # bypass manual verification
                        **{
                            field_name: data.get(field_name, "")
                            for field_name in user_fields
                        },
                    },
                )
                if created:  # Only when registering a new user.
                    user.set_password(password)
                    user.save()

                user_profile_program_data = {
                    k: v
                    for k, v in data.items()
                    if k not in user_fields and k != "password"
                }
                user_profile_program_data = strip_registration_consent_keys(
                    user_profile_program_data
                )

                create_participant_consent(program=program, user=user, request=request)
                PartnerProgramUserProfile.objects.create(
                    partner_program_data=user_profile_program_data,
                    user=user,
                    partner_program=program,
                )
        except IntegrityError:
            return Response(
                data={"detail": "User has already registered in this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_email.delay(
            UserProgramRegisterParams(
                message_type=MessageTypeEnum.REGISTERED_PROGRAM_USER.value,
                user_id=user.id,
                program_name=program.name,
                program_id=program.id,
                schema_id=2,
            )
        )
        return Response(status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        return Response(status=status.HTTP_200_OK)


class PartnerProgramRegister(generics.GenericAPIView):
    """
    Register user to program and save additional program data
    """

    queryset = PartnerProgram.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramUserSerializer

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            if program.status != PartnerProgram.STATUS_PUBLISHED:
                return Response(
                    data={
                        "detail": "Registration for this program is not available.",
                        "current_status": program.status,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if program.is_private:
                return Response(
                    data={"detail": "Registration for this program is invite-only."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if program.datetime_registration_ends < timezone.now():
                return Response(
                    data={"detail": "Registration period has ended."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user_to_add = request.user
            user_profile_program_data = strip_registration_consent_keys(
                dict(request.data.items())
            )

            with transaction.atomic():
                create_participant_consent(
                    program=program,
                    user=user_to_add,
                    request=request,
                )
                added_user_profile = PartnerProgramUserProfile(
                    partner_program_data=user_profile_program_data,
                    user=user_to_add,
                    partner_program=program,
                )
                added_user_profile.save()

            send_email.delay(
                UserProgramRegisterParams(
                    message_type=MessageTypeEnum.REGISTERED_PROGRAM_USER.value,
                    user_id=user_to_add.id,
                    program_name=program.name,
                    program_id=program.id,
                    schema_id=2,
                )
            )

            return Response(status=status.HTTP_201_CREATED)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except IntegrityError:
            return Response(
                data={"detail": "User already registered to this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class PartnerProgramSetViewed(generics.GenericAPIView):
    queryset = PartnerProgram.objects.none()
    serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            add_view(program, request.user)
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramSetLiked(generics.CreateAPIView):
    queryset = PartnerProgram.objects.none()
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            set_like(program, request.user, request.data.get("is_liked"))
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramDataSchema(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramDataSchemaSerializer
    permission_classes = [permissions.IsAuthenticated]


class PartnerProgramFieldValueBulkUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramFieldValueUpdateSerializer

    def get_project(self, project_id):
        try:
            return Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            raise NotFound("Проект не найден")

    @swagger_auto_schema(request_body=PartnerProgramFieldValueUpdateSerializer(many=True))
    def put(self, request, project_id, *args, **kwargs):
        project = self.get_project(project_id)

        if project.leader != request.user:
            raise PermissionDenied("Вы не являетесь лидером этого проекта")

        try:
            program_project = PartnerProgramProject.objects.select_related(
                "partner_program"
            ).get(project=project)
        except PartnerProgramProject.DoesNotExist:
            raise ValidationError("Проект не привязан ни к одной программе")

        partner_program = program_project.partner_program

        if partner_program.is_competitive and program_project.submitted:
            raise ValidationError(
                "Нельзя изменять значения полей программы после сдачи проекта на проверку."
            )

        serializer = self.serializer_class(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            for item in serializer.validated_data:
                field = item["field"]

                if field.partner_program_id != partner_program.id:
                    raise ValidationError(
                        f"Поле с id={field.id} не относится к программе этого проекта"
                    )

                value_text = item.get("value_text")

                obj, created = PartnerProgramFieldValue.objects.update_or_create(
                    program_project=program_project,
                    field=field,
                    defaults={"value_text": value_text},
                )

                if created:
                    try:
                        obj.full_clean()
                    except ValidationError as e:
                        raise ValidationError(e.message_dict)

        return Response(
            {"detail": "Значения успешно обновлены"},
            status=status.HTTP_200_OK,
        )


class PartnerProgramProjectSubmitView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsProjectLeader]
    serializer_class = EmptySerializer
    queryset = PartnerProgramProject.objects.all()

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                name="id",
                in_=openapi.IN_PATH,
                description="Уникальный идентификатор связи проекта и программы",
                type=openapi.TYPE_INTEGER,
                required=True,
            ),
        ]
    )
    def post(self, request, pk, *args, **kwargs):
        program_project = self.get_object()

        if not program_project.partner_program.is_competitive:
            return Response(
                {"detail": "Программа не является конкурсной."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if program_project.submitted:
            return Response(
                {"detail": "Проект уже был сдан на проверку."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not program_project.partner_program.is_project_submission_open():
            return Response(
                {"detail": "Срок подачи проектов в программу завершён."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_project_team_size_for_program(
                program=program_project.partner_program,
                project=program_project.project,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        program_project.submitted = True
        program_project.datetime_submitted = now()
        program_project.save()

        return Response(
            {"detail": "Проект успешно сдан на проверку."},
            status=status.HTTP_200_OK,
        )


class ProgramFiltersAPIView(APIView):
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]

    def get(self, request, pk):
        program = get_object_or_404(PartnerProgram, pk=pk)
        fields = PartnerProgramField.objects.filter(
            partner_program=program, show_filter=True
        )
        serializer = PartnerProgramFieldSerializer(fields, many=True)
        return Response(serializer.data)


class ProgramProjectFilterAPIView(GenericAPIView):
    serializer_class = ProgramProjectFilterRequestSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    pagination_class = PartnerProgramPagination
    queryset = PartnerProgram.objects.none()

    def post(self, request, pk):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        program = get_object_or_404(PartnerProgram, pk=pk)
        filters = data.get("filters", {})

        field_names = list(filters.keys())
        field_qs = PartnerProgramField.objects.filter(
            partner_program=program, name__in=field_names
        )
        field_by_name = {f.name: f for f in field_qs}

        missing = [name for name in field_names if name not in field_by_name]
        if missing:
            return Response(
                {"detail": f"Поля не найденные в программе: {missing}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for field_name, values in filters.items():
            field_obj = field_by_name[field_name]
            if not field_obj.show_filter:
                return Response(
                    {
                        "detail": f"Поле '{field_name}' недоступно для фильтрации (show_filter=False)."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            opts = field_obj.get_options_list()
            if opts:
                invalid_values = [val for val in values if val not in opts]
                if invalid_values:
                    return Response(
                        {
                            "detail": f"Неверные значения для поля '{field_name}'.",
                            "invalid": invalid_values,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {"detail": f"Поле '{field_name}' не имеет вариантов (options)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        qs = filter_program_projects_by_field_name(program, filters)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        projects = [pp.project for pp in page]
        serializer_out = ProjectListSerializer(
            projects, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer_out.data)


class PartnerProgramProjectsAPIView(generics.ListAPIView):
    """
    Список всех проектов участников конкретной партнёрской программы.
    Доступ разрешён только менеджерам и администраторам программы.
    """

    serializer_class = ProjectListSerializer
    permission_classes = [IsAuthenticated, IsAdminOrManagerOfProgram]
    pagination_class = PartnerProgramPagination

    def get_queryset(self):
        if "pk" not in self.kwargs:
            return Project.objects.none()

        program = get_object_or_404(PartnerProgram, pk=self.kwargs["pk"])
        return Project.objects.filter(program_links__partner_program=program).distinct()


class PartnerProgramAnalyticsAPIView(APIView):
    permission_classes = [IsAdminOrManagerOfProgram]

    def get(self, request, pk: int):
        program = get_object_or_404(PartnerProgram, pk=pk)
        contacts_visible = can_view_participant_contacts(request.user, program)
        log_personal_data_access(
            actor=request.user,
            program=program,
            action="participant_list_view",
            object_type="analytics",
            object_id=program.id,
            metadata={
                "count": PartnerProgramUserProfile.objects.filter(
                    partner_program=program
                ).count(),
                "masked": not contacts_visible,
                "request_path": request.path,
            },
        )
        payload = build_program_analytics_payload(program)
        payload["can_export_contacts"] = contacts_visible
        payload["verification_status"] = program.verification_status
        return Response(payload, status=status.HTTP_200_OK)


class PartnerProgramAnalyticsExportAPIView(APIView):
    permission_classes = [IsAdminOrManagerOfProgram]

    def get(self, request, pk: int):
        program = get_object_or_404(PartnerProgram, pk=pk)
        binary_data = build_program_analytics_xlsx(program, include_contacts=False)
        log_personal_data_access(
            actor=request.user,
            program=program,
            action="participant_export_download",
            object_type="xlsx",
            object_id=program.id,
            metadata={
                "count": PartnerProgramUserProfile.objects.filter(
                    partner_program=program
                ).count(),
                "export_type": "analytics_basic",
                "field_names": ["participant_id", "full_name", "project", "role"],
                "masked": True,
                "request_path": request.path,
            },
        )
        date_suffix = timezone.now().strftime("%d.%m.%y")
        base_name = f"analytics - {program.name or 'program'} - {date_suffix}"
        return build_xlsx_download_response(binary_data, base_name=base_name)


class PartnerProgramAnalyticsContactExportAPIView(APIView):
    permission_classes = [IsAdminOrManagerOfProgram]

    def get(self, request, pk: int):
        program = get_object_or_404(PartnerProgram, pk=pk)
        if not can_view_participant_contacts(request.user, program):
            return Response(
                {
                    "detail": "Contact export is available only after company verification.",
                    "verification_status": program.verification_status,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        binary_data = build_program_analytics_xlsx(program, include_contacts=True)
        row_count = PartnerProgramUserProfile.objects.filter(
            partner_program=program
        ).count()
        log_personal_data_access(
            actor=request.user,
            program=program,
            action="participant_export_download",
            object_type="xlsx",
            object_id=program.id,
            metadata={
                "count": row_count,
                "export_type": "analytics_contacts",
                "field_names": ["email", "phone_number"],
                "masked": False,
                "request_path": request.path,
            },
        )
        date_suffix = timezone.now().strftime("%d.%m.%y")
        base_name = f"contacts - {program.name or 'program'} - {date_suffix}"
        return build_xlsx_download_response(binary_data, base_name=base_name)


class PartnerProgramExportRatesAPIView(APIView):
    """Возвращает Excel-файл с оценками проектов программы."""

    permission_classes = [IsAdminOrManagerOfProgram]

    def get(self, request, pk: int):
        try:
            program = PartnerProgram.objects.get(pk=pk)
        except PartnerProgram.DoesNotExist:
            return Response(
                {"detail": "Программа не найдена."}, status=status.HTTP_404_NOT_FOUND
            )

        user = request.user
        if not (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or program.is_manager(user)
        ):
            return Response(
                {"detail": "Недостаточно прав."}, status=status.HTTP_403_FORBIDDEN
            )

        rates_data_to_write = prepare_project_scores_export_data(program.id)
        xlsx_file_writer = XlsxFileToExport()
        xlsx_file_writer.write_data_to_xlsx(rates_data_to_write)
        binary_data_to_export: bytes = xlsx_file_writer.get_binary_data_from_self_file()
        xlsx_file_writer.clear_buffer()

        date_suffix = timezone.now().strftime("%d.%m.%y")
        base_name = f"scores - {program.name or 'program'} - {date_suffix}"
        return build_xlsx_download_response(binary_data_to_export, base_name=base_name)


class PartnerProgramExportProjectsAPIView(APIView):
    """Возвращает Excel-файл со всеми проектами программы."""

    permission_classes = [IsAdminOrManagerOfProgram]

    def _get_program(self, pk: int) -> PartnerProgram | None:
        try:
            return PartnerProgram.objects.get(pk=pk)
        except PartnerProgram.DoesNotExist:
            return None

    def _has_access(self, user, program: PartnerProgram) -> bool:
        return bool(
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or program.is_manager(user)
        )

    def _export(self, program: PartnerProgram, only_submitted: bool):
        extra_cols = build_program_field_columns(program)
        header_pairs = BASE_COLUMNS + extra_cols

        fv_qs = PartnerProgramFieldValue.objects.select_related("field").filter(
            field__partner_program_id=program.id
        )
        links_qs = program.program_projects.select_related(
            "project", "project__leader"
        ).prefetch_related(
            Prefetch("field_values", queryset=fv_qs, to_attr="_prefetched_field_values"),
            Prefetch(
                "project__collaborator_set",
                queryset=Collaborator.objects.select_related("user"),
                to_attr="_prefetched_collaborators",
            ),
        )
        if only_submitted:
            links_qs = links_qs.filter(submitted=True)

        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title="Проекты")
        ws.append([title for _, title in header_pairs])

        extra_keys_order = [key for key, _ in extra_cols]

        for row_number, program_project_link in enumerate(links_qs, start=1):
            row_dict = row_dict_for_link(
                program_project_link=program_project_link,
                extra_field_keys_order=extra_keys_order,
                row_number=row_number,
            )
            raw_values = [row_dict.get(key, "") for key, _ in header_pairs]
            safe_values = [sanitize_excel_value(v) for v in raw_values]
            ws.append(safe_values)

        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)

        label = "projects_review" if only_submitted else "projects"
        date_suffix = timezone.now().strftime("%d.%m.%y")
        base_name = f"{label} - {program.name or 'program'} - {date_suffix}"
        return build_xlsx_download_response(bio.getvalue(), base_name=base_name)

    def get(self, request, pk: int):
        program = self._get_program(pk)
        if not program:
            return Response(
                {"detail": "Программа не найдена."}, status=status.HTTP_404_NOT_FOUND
            )

        if not self._has_access(request.user, program):
            return Response(
                {"detail": "Недостаточно прав."}, status=status.HTTP_403_FORBIDDEN
            )

        only_submitted = request.query_params.get("only_submitted") in (
            "1",
            "true",
            "True",
        )
        return self._export(program=program, only_submitted=only_submitted)

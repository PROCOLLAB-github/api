from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from partner_programs.models import PartnerProgram
from partner_programs.services.management import managed_program
from project_rates import workspace as service
from project_rates.models import ExpertInvitation
from users.models import CustomUser


class InvitationThrottle(AnonRateThrottle):
    rate = "30/min"


class InvitationEmail(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class RevisionWrite(serializers.Serializer):
    revision = serializers.CharField(max_length=64)


class AssignmentWrite(RevisionWrite):
    project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), max_length=10000
    )


class AllocationWrite(serializers.Serializer):
    expert_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=1000
    )
    project_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=10000
    )


class QuotaWrite(serializers.Serializer):
    required_evaluators = serializers.IntegerField(min_value=1, max_value=1000)
    revision = serializers.CharField(max_length=64, required=False)


def validated(serializer_type, data):
    serializer = serializer_type(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class PrivateView(APIView):
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response


class ExpertsView(PrivateView):
    def get(self, request, pk):
        return Response(service.workspace_data(managed_program(pk, request.user)))

    def post(self, request, pk):
        data = validated(InvitationEmail, request.data)
        return Response(service.invite(pk, request.user, data["email"]), status=201)


class InvitationActionView(PrivateView):
    def post(self, request, pk, invitation_id, action):
        if action == "revoke":
            service.revoke(pk, request.user, invitation_id)
            return Response(status=204)
        if action == "resend":
            program = managed_program(pk, request.user)
            invitation = get_object_or_404(program.expert_invitations, pk=invitation_id)
            return Response(
                service.invite(
                    pk, request.user, invitation.email, invitation_id=invitation_id
                )
            )
        return Response(status=404)


class ExpertAssignmentsView(PrivateView):
    def get(self, request, pk, expert_id):
        return Response(
            service.assignment_options(managed_program(pk, request.user), expert_id)
        )

    def put(self, request, pk, expert_id):
        data = validated(AssignmentWrite, request.data)
        return Response(service.save_assignments(pk, request.user, expert_id, data))


class AllocationView(PrivateView):
    @transaction.atomic
    def post(self, request, pk):
        return Response(
            service.allocation(
                managed_program(pk, request.user, lock=True),
                validated(AllocationWrite, request.data),
            )
        )


class AllocationApplyView(PrivateView):
    def post(self, request, pk):
        token = serializers.CharField(max_length=500000).run_validation(
            request.data.get("plan_token")
        )
        return Response(service.apply_allocation(pk, request.user, token))


class EvaluatorsView(PrivateView):
    @transaction.atomic
    def post(self, request, pk):
        data = validated(QuotaWrite, request.data)
        return Response(
            service.quota_preview(
                managed_program(pk, request.user, lock=True), data["required_evaluators"]
            )
        )

    def put(self, request, pk):
        data = validated(QuotaWrite, request.data)
        if "revision" not in data:
            raise ValidationError(
                {"revision": "Обновите предпросмотр перед сохранением."}
            )
        return Response(service.save_quota(pk, request.user, data))


class MyProgramsView(PrivateView):
    def get(self, request):
        return Response(service.my_programs(request.user))


class AcceptOwnInvitationView(PrivateView):
    @transaction.atomic
    def post(self, request, invitation_id):
        invitation = get_object_or_404(
            ExpertInvitation, pk=invitation_id, email__iexact=request.user.email
        )
        PartnerProgram.objects.select_for_update().get(pk=invitation.partner_program_id)
        invitation = ExpertInvitation.objects.select_for_update().get(pk=invitation.pk)
        service.accept_invitation(invitation, request.user)
        return Response({"program_id": invitation.partner_program_id, "accepted": True})


class InvitedRegistration(serializers.ModelSerializer):
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)
    repeat_password = serializers.CharField(write_only=True)
    accept_policy = serializers.BooleanField()
    accept_age = serializers.BooleanField()

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "password",
            "repeat_password",
            "accept_policy",
            "accept_age",
        ]

    def validate(self, attrs):
        if not attrs["accept_policy"] or not attrs["accept_age"]:
            raise ValidationError("Подтвердите согласия платформы.")
        if attrs["password"] != attrs["repeat_password"]:
            raise ValidationError({"repeat_password": "Пароли не совпадают."})
        candidate = CustomUser(
            first_name=attrs["first_name"],
            last_name=attrs["last_name"],
            email=self.context["email"],
        )
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as error:
            raise ValidationError({"password": error.messages})
        return attrs


class PublicInvitationView(PrivateView):
    permission_classes = [AllowAny]
    throttle_classes = [InvitationThrottle]

    def get(self, request, token):
        invitation = service.token_invitation(token, allow_accepted=True)
        login_email = (
            CustomUser.objects.filter(email__iexact=invitation.email)
            .values_list("email", flat=True)
            .first()
        )
        return Response(
            {
                **service.invitation_data(invitation),
                "program": service.program_card(invitation.partner_program),
                "account_exists": login_email is not None,
                "login_email": login_email or invitation.email,
                "matches_account": bool(
                    request.user.is_authenticated
                    and request.user.email.lower() == invitation.email
                ),
            }
        )


class PublicInvitationActionView(PublicInvitationView):
    def get(self, request, token, action):
        return Response(status=405)

    def post(self, request, token, action):
        try:
            with transaction.atomic():
                invitation = service.token_invitation(token, allow_accepted=True)
                PartnerProgram.objects.select_for_update().get(
                    pk=invitation.partner_program_id
                )
                invitation = service.token_invitation(
                    token, lock=True, allow_accepted=True
                )
                if action == "accept":
                    service.accept_invitation(invitation, request.user)
                    return Response(
                        {"program_id": invitation.partner_program_id, "accepted": True}
                    )
                if action != "register":
                    return Response(status=404)
                if (
                    invitation.status != "pending"
                    or invitation.expires_at <= timezone.now()
                ):
                    raise service.InvitationGone()
                if request.user.is_authenticated:
                    raise PermissionDenied(
                        "Для существующего аккаунта примите приглашение после входа."
                    )
                if CustomUser.objects.filter(email__iexact=invitation.email).exists():
                    raise service.WorkspaceConflict(
                        "account_exists",
                        "Аккаунт с этой почтой уже есть. Войдите, чтобы принять приглашение.",
                    )
                form = InvitedRegistration(
                    data=request.data, context={"email": invitation.email}
                )
                form.is_valid(raise_exception=True)
                values = form.validated_data
                user = CustomUser.objects.create_user(
                    email=invitation.email,
                    first_name=values["first_name"],
                    last_name=values["last_name"],
                    password=values["password"],
                    birthday=None,
                    user_type=CustomUser.EXPERT,
                    is_active=True,
                    onboarding_stage=None,
                )
                service.accept_invitation(invitation, user)
                refresh = RefreshToken.for_user(user)
                return Response(
                    {
                        "access": str(refresh.access_token),
                        "refresh": str(refresh),
                        "program_id": invitation.partner_program_id,
                    },
                    status=201,
                )
        except IntegrityError:
            raise service.WorkspaceConflict(
                "account_exists",
                "Аккаунт уже создан. Войдите, чтобы принять приглашение.",
            )

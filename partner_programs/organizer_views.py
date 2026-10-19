from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from partner_programs.models import PartnerProgram
from partner_programs.services import organizers as service
from partner_programs.services.management import managed_program
from project_rates.workspace import invited_account, invitation_data, program_card
from project_rates.workspace_views import (
    InvitationEmail,
    InvitationThrottle,
    InvitedRegistration,
    PrivateView,
    RevisionWrite,
    validated,
)
from users.models import CustomUser
from users.validators import user_birthday_validator


class InviteWrite(InvitationEmail, RevisionWrite):
    pass


class OrganizersView(PrivateView):
    @transaction.atomic
    def get(self, request, pk):
        return Response(
            service.organizer_data(
                managed_program(pk, request.user, lock=True), request.user
            )
        )

    def post(self, request, pk):
        data = validated(InviteWrite, request.data)
        return Response(
            service.invite(pk, request.user, data["email"], data["revision"]), status=201
        )


class OrganizerInvitationActionView(PrivateView):
    def post(self, request, pk, invitation_id, action):
        data = validated(RevisionWrite, request.data)
        if action == "revoke":
            return Response(
                service.revoke(pk, request.user, invitation_id, data["revision"])
            )
        if action == "resend":
            program = managed_program(pk, request.user)
            from django.shortcuts import get_object_or_404

            invitation = get_object_or_404(
                program.organizer_invitations, pk=invitation_id
            )
            return Response(
                service.invite(
                    pk,
                    request.user,
                    invitation.email,
                    data["revision"],
                    invitation_id=invitation_id,
                )
            )
        return Response(status=404)


class OrganizerAccessView(PrivateView):
    def post(self, request, pk, user_id):
        data = validated(RevisionWrite, request.data)
        return Response(service.remove(pk, request.user, user_id, data["revision"]))


class OrganizerRegistration(InvitedRegistration):
    birthday = serializers.DateField(
        required=True, allow_null=False, validators=[user_birthday_validator]
    )

    class Meta(InvitedRegistration.Meta):
        fields = [*InvitedRegistration.Meta.fields, "birthday"]


class PublicOrganizerInvitationView(PrivateView):
    permission_classes = [AllowAny]
    throttle_classes = [InvitationThrottle]

    def get(self, request, token):
        invitation = service.token_invitation(token, allow_accepted=True)
        accounts = list(CustomUser.objects.filter(email__iexact=invitation.email))
        account = invited_account(accounts)
        return Response(
            {
                **invitation_data(invitation),
                "purpose": "organizer",
                "program": program_card(invitation.partner_program),
                "account_exists": bool(accounts),
                "login_email": account.email if account else invitation.email,
                "matches_account": bool(
                    request.user.is_authenticated
                    and request.user.email.lower() == invitation.email.lower()
                ),
            }
        )


class PublicOrganizerInvitationActionView(PublicOrganizerInvitationView):
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
                if invitation.status != "pending":
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
                form = OrganizerRegistration(
                    data=request.data, context={"email": invitation.email}
                )
                form.is_valid(raise_exception=True)
                values = form.validated_data
                user = CustomUser.objects.create_user(
                    email=invitation.email,
                    first_name=values["first_name"],
                    last_name=values["last_name"],
                    password=values["password"],
                    birthday=values["birthday"],
                    user_type=CustomUser.MEMBER,
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

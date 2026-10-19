"""Program-scoped access. Membership writes serialize on the program row."""

import json
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from partner_programs.models import OrganizerInvitation
from partner_programs.services.management import managed_program, person_name
from project_rates.workspace import (
    InvitationGone,
    WorkspaceConflict,
    digest,
    invited_account,
    invitation_data,
)
from users.models import CustomUser


def revision(program):
    data = [
        list(program.managers.order_by("pk").values_list("pk", "is_active")),
        list(
            program.organizer_invitations.order_by("pk").values_list(
                "pk", "status", "token_digest", "expires_at"
            )
        ),
    ]
    return digest(json.dumps(data, default=str))


def check_revision(program, expected):
    if expected != revision(program):
        raise WorkspaceConflict(
            "stale_organizers", "Состав организаторов изменился. Обновите список."
        )


def organizer_data(program, user):
    members = list(program.managers.order_by("pk"))
    active_count = sum(member.is_active for member in members)
    rows = [
        {
            "id": f"member:{member.pk}",
            "user_id": member.pk,
            "name": person_name(member),
            "email": member.email,
            "avatar": member.avatar,
            "status": "joined",
            "active": member.is_active,
            "is_self": member.pk == user.pk,
            "can_remove": not (member.is_active and active_count <= 1),
        }
        for member in members
    ]
    invitations = list(
        program.organizer_invitations.filter(status="pending").order_by("pk")
    )
    accounts = {}
    for account in CustomUser.objects.annotate(invitation_email=Lower("email")).filter(
        invitation_email__in=[i.email.lower() for i in invitations]
    ):
        accounts.setdefault(account.invitation_email, []).append(account)
    member_emails = {m.email.lower() for m in members}
    for invitation in invitations:
        if invitation.email.lower() in member_emails:
            continue
        account = invited_account(accounts.get(invitation.email.lower(), []))
        rows.append(
            {
                **invitation_data(invitation),
                "id": f"invite:{invitation.pk}",
                "invitation_id": invitation.pk,
                "name": person_name(account) if account else None,
                "avatar": account.avatar if account else None,
                "is_self": False,
                "can_remove": False,
            }
        )
    return {
        "revision": revision(program),
        "organizers": rows,
        "organizer_count": len(members),
        "active_organizer_count": active_count,
        "invitation_count": sum(row["status"] != "joined" for row in rows),
    }


@transaction.atomic
def invite(program_id, user, email, expected, *, invitation_id=None):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, expected)
    email = email.strip().lower()
    if program.managers.filter(email__iexact=email).exists():
        raise WorkspaceConflict(
            "already_organizer", "У этого пользователя уже есть доступ."
        )
    if invitation_id is None:
        previous = program.organizer_invitations.filter(
            email__iexact=email, status="pending"
        ).first()
        if previous and previous.expires_at > timezone.now():
            raise WorkspaceConflict(
                "already_invited", "Приглашение уже есть. Можно отправить его повторно."
            )
        if previous:
            previous.status = "revoked"
            previous.save(update_fields=["status", "updated_at"])
        invitation = OrganizerInvitation(
            partner_program=program, email=email, invited_by=user
        )
    else:
        invitation = get_object_or_404(program.organizer_invitations, pk=invitation_id)
        if invitation.status != "pending":
            raise WorkspaceConflict(
                "invitation_resolved",
                "Приглашение уже принято или отозвано. Обновите список.",
            )
    token = secrets.token_urlsafe(32)
    invitation.token_digest = digest(token)
    invitation.delivery_status = "queued"
    invitation.expires_at = timezone.now() + timedelta(days=7)
    invitation.save()
    from partner_programs.tasks import send_organizer_invitation

    def enqueue():
        try:
            send_organizer_invitation.apply_async(
                (invitation.pk, token), argsrepr=f"({invitation.pk}, '[redacted]')"
            )
        except Exception:
            OrganizerInvitation.objects.filter(
                pk=invitation.pk, token_digest=digest(token)
            ).update(delivery_status="failed")

    transaction.on_commit(enqueue)
    return organizer_data(program, user)


@transaction.atomic
def revoke(program_id, user, invitation_id, expected):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, expected)
    invitation = get_object_or_404(program.organizer_invitations, pk=invitation_id)
    if invitation.status != "pending":
        raise WorkspaceConflict(
            "invitation_resolved",
            "Приглашение уже принято или отозвано. Обновите список.",
        )
    invitation.status = "revoked"
    invitation.save(update_fields=["status", "updated_at"])
    return organizer_data(program, user)


@transaction.atomic
def remove(program_id, user, member_id, expected):
    program = managed_program(program_id, user, lock=True)
    check_revision(program, expected)
    member = get_object_or_404(program.managers, pk=member_id)
    if member.is_active and program.managers.filter(is_active=True).count() <= 1:
        raise WorkspaceConflict(
            "last_organizer",
            "Нельзя убрать последнего организатора. Сначала пригласите коллегу и дождитесь принятия.",
        )
    program.managers.remove(member)
    program.organizer_invitations.filter(
        Q(accepted_by=member) | Q(email__iexact=member.email)
    ).exclude(status="revoked").update(status="revoked", updated_at=timezone.now())
    if member.pk == user.pk:
        return {"access_removed": True, "program_id": program.pk}
    return organizer_data(program, user)


def token_invitation(token, *, lock=False, allow_accepted=False):
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        raise Http404
    rows = (
        OrganizerInvitation.objects.select_for_update()
        if lock
        else OrganizerInvitation.objects
    )
    invitation = get_object_or_404(
        rows.select_related("partner_program"), token_digest=digest(token)
    )
    if invitation.status == "accepted" and allow_accepted:
        if invitation.partner_program.managers.filter(
            pk=invitation.accepted_by_id
        ).exists():
            return invitation
        raise InvitationGone()
    if invitation.status != "pending" or invitation.expires_at <= timezone.now():
        raise InvitationGone()
    return invitation


def accept_invitation(invitation, user):
    if (
        not user.is_authenticated
        or not user.is_active
        or user.email.lower() != invitation.email.lower()
    ):
        raise PermissionDenied("Войдите в аккаунт с почтой из приглашения.")
    if invitation.status == "accepted":
        if invitation.accepted_by_id != user.pk:
            raise PermissionDenied()
        if not invitation.partner_program.managers.filter(pk=user.pk).exists():
            raise InvitationGone()
        return
    if invitation.status != "pending" or invitation.expires_at <= timezone.now():
        raise InvitationGone()
    invitation.partner_program.managers.add(user)
    invitation.status = "accepted"
    invitation.accepted_by = user
    invitation.save(update_fields=["status", "accepted_by", "updated_at"])

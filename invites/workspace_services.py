from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from invites.models import Invite
from notifications.events import (
    notify_project_invite_created,
    notify_project_invite_resolved,
)
from partner_programs.models import PartnerProgramUserProfile
from projects.models import Collaborator, Project

User = get_user_model()


class ProjectInvitationServiceError(Exception):
    """Базовая контролируемая ошибка lifecycle приглашения в Project."""

    code = "project_invitation_error"
    default_detail = "Операция с приглашением недоступна."
    default_field = "non_field_errors"

    def __init__(self, detail=None, *, field=None):
        self.detail = detail or self.default_detail
        self.field = field or self.default_field
        super().__init__(self.detail)


class ProjectInvitationPermissionError(ProjectInvitationServiceError):
    code = "project_invitation_permission_denied"
    default_detail = "У вас нет прав для управления приглашениями проекта."
    default_field = "project"


class ProjectInvitationNotPendingError(ProjectInvitationServiceError):
    code = "project_invitation_not_pending"
    default_detail = "Приглашение уже обработано и не может быть изменено."
    default_field = "status"


class ProjectInvitationTargetInvalidError(ProjectInvitationServiceError):
    code = "project_invitation_target_invalid"
    default_detail = "Пользователя нельзя пригласить в этот проект."
    default_field = "recipient_id"


class ProjectInvitationDuplicateError(ProjectInvitationServiceError):
    code = "project_invitation_duplicate"
    default_detail = "Активное приглашение для этого пользователя уже существует."
    default_field = "recipient_id"


class ProjectInvitationNotOwnedError(ProjectInvitationServiceError):
    code = "project_invitation_not_owned"
    default_detail = "Это приглашение предназначено другому пользователю."
    default_field = "invitation"


def can_manage_project_invitations(user, project: Project) -> bool:
    """Разрешает управление только лидеру Project и административным ролям."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.is_superuser or project.leader_id == user.pk)
    )


def _require_pending(invitation: Invite) -> None:
    if not invitation.is_pending:
        raise ProjectInvitationNotPendingError()


def _require_eligible_recipient(*, project: Project, recipient: User) -> None:
    if project.leader_id == recipient.pk:
        raise ProjectInvitationTargetInvalidError("Руководитель уже состоит в проекте.")
    if Collaborator.objects.filter(project=project, user=recipient).exists():
        raise ProjectInvitationTargetInvalidError(
            "Пользователь уже является участником проекта."
        )

    # Legacy Project может быть напрямую связан с одной PartnerProgram.
    # Повторяем invariant Collaborator.clean(), иначе принятие заведомо упадет.
    program_link = project.program_links.only("partner_program_id").first()
    if (
        program_link
        and not PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_link.partner_program_id,
            user=recipient,
        ).exists()
    ):
        raise ProjectInvitationTargetInvalidError(
            "Пользователь не является участником программы проекта."
        )


def _lock_invitation_graph(invitation_id: int) -> tuple[Project, Invite]:
    """Блокирует Project и Invite в едином порядке для всех переходов статуса."""
    reference = Invite.objects.only("project_id").get(pk=invitation_id)
    project = Project.objects.select_for_update().get(pk=reference.project_id)
    invitation = Invite.objects.select_for_update().get(pk=invitation_id)
    return project, invitation


def create_project_invitation(
    *,
    project_id: int,
    actor: User,
    recipient: User,
    role: str | None = None,
    specialization: str | None = None,
    motivational_letter: str | None = None,
) -> Invite:
    """Создает единственное pending-приглашение под блокировкой Project."""
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=project_id)
        if not can_manage_project_invitations(actor, project):
            raise ProjectInvitationPermissionError()
        _require_eligible_recipient(project=project, recipient=recipient)

        pending = Invite.objects.select_for_update().filter(
            project=project,
            user=recipient,
            is_accepted__isnull=True,
            is_revoked=False,
        )
        if pending.exists():
            raise ProjectInvitationDuplicateError()

        try:
            # Savepoint сохраняет внешнюю транзакцию пригодной для проверки
            # partial unique constraint после конкурентного INSERT.
            with transaction.atomic():
                invitation = Invite.objects.create(
                    project=project,
                    user=recipient,
                    invited_by=actor,
                    role=role,
                    specialization=specialization,
                    motivational_letter=motivational_letter,
                )
        except IntegrityError as exc:
            if pending.exists():
                raise ProjectInvitationDuplicateError() from exc
            raise
        notify_project_invite_created(invitation)
        return invitation


def accept_project_invitation(*, invitation_id: int, actor: User) -> Invite:
    """Атомарно принимает приглашение и создает Collaborator один раз."""
    with transaction.atomic():
        project, invitation = _lock_invitation_graph(invitation_id)
        if invitation.user_id != actor.pk:
            raise ProjectInvitationNotOwnedError()
        _require_pending(invitation)
        recipient = User.objects.get(pk=invitation.user_id)
        _require_eligible_recipient(project=project, recipient=recipient)

        Collaborator.objects.create(
            project=project,
            user=recipient,
            role=invitation.role,
            specialization=invitation.specialization,
        )
        invitation.is_accepted = True
        invitation.resolved_at = timezone.now()
        invitation.save(update_fields=["is_accepted", "resolved_at", "datetime_updated"])
        notify_project_invite_resolved(invitation, actor=actor, status="accepted")
        return invitation


def decline_project_invitation(*, invitation_id: int, actor: User) -> Invite:
    """Завершает pending-приглашение решением его получателя."""
    with transaction.atomic():
        _project, invitation = _lock_invitation_graph(invitation_id)
        if invitation.user_id != actor.pk:
            raise ProjectInvitationNotOwnedError()
        _require_pending(invitation)
        invitation.is_accepted = False
        invitation.resolved_at = timezone.now()
        invitation.save(update_fields=["is_accepted", "resolved_at", "datetime_updated"])
        notify_project_invite_resolved(invitation, actor=actor, status="declined")
        return invitation


def revoke_project_invitation(*, invitation_id: int, actor: User) -> Invite:
    """Сохраняет отзыв в истории вместо физического удаления Invite."""
    with transaction.atomic():
        project, invitation = _lock_invitation_graph(invitation_id)
        if not can_manage_project_invitations(actor, project):
            raise ProjectInvitationPermissionError()
        _require_pending(invitation)
        invitation.is_revoked = True
        invitation.resolved_at = timezone.now()
        invitation.save(update_fields=["is_revoked", "resolved_at", "datetime_updated"])
        notify_project_invite_resolved(invitation, actor=actor, status="revoked")
        return invitation

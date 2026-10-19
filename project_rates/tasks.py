from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from procollab.celery import app


@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_expert_invitation(invitation_id, token):
    from project_rates.models import ExpertInvitation
    from project_rates.workspace import digest

    rows = ExpertInvitation.objects.filter(
        pk=invitation_id,
        token_digest=digest(token),
        status="pending",
        expires_at__gt=timezone.now(),
    )
    invitation = rows.select_related("partner_program").first()
    if not invitation:
        return
    context = {
        "program_name": invitation.partner_program.name,
        "email": invitation.email,
        "invitation_url": settings.EXPERT_WORKSPACE_FRONTEND_URL.rstrip("/")
        + "/expert-invitation/"
        + token,
        "expires_at": invitation.expires_at,
        "logo_url": "https://786505.selcdn.ru/app_files/procollab_logo.png",
    }
    try:
        message = EmailMultiAlternatives(
            "Приглашение эксперта | PROCOLLAB",
            render_to_string("email/expert_invitation.txt", context),
            settings.EMAIL_USER,
            [invitation.email],
        )
        message.attach_alternative(
            render_to_string("email/expert_invitation.html", context), "text/html"
        )
        if not message.send():
            raise RuntimeError("Invitation delivery did not complete")
        rows.update(delivery_status="sent")
    except Exception:
        rows.update(delivery_status="failed")
        raise


@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_expert_joined_notification(notification_id):
    from django.db import transaction
    from project_rates.models import ExpertJoinedNotification

    # Serializes duplicate deliveries of the same task; acceptance itself is idempotent.
    with transaction.atomic():
        notice = (
            ExpertJoinedNotification.objects.select_for_update()
            .filter(pk=notification_id)
            .first()
        )
        if not notice or notice.emailed_at:
            return
        program = notice.invitation.partner_program
        recipient = program.managers.filter(
            pk=notice.recipient_id, is_active=True
        ).first()
        if not recipient or not recipient.email:
            return
        context = {
            "program_name": program.name,
            "expert_name": notice.expert_name,
            "expert_email": notice.expert_email,
            "program_url": settings.EXPERT_WORKSPACE_FRONTEND_URL.rstrip("/")
            + f"/office/program/{program.pk}/management/experts",
        }
        message = EmailMultiAlternatives(
            "Эксперт принял приглашение | PROCOLLAB",
            render_to_string("email/expert_joined.txt", context),
            settings.EMAIL_USER,
            [recipient.email],
        )
        message.attach_alternative(
            render_to_string("email/expert_joined.html", context), "text/html"
        )
        if not message.send():
            raise RuntimeError("Expert joined receipt delivery did not complete")
        notice.emailed_at = timezone.now()
        notice.save(update_fields=["emailed_at"])

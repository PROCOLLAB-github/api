import logging

from procollab.celery import app
from partner_programs.services import publish_finished_program_projects

logger = logging.getLogger(__name__)


@app.task
def publish_finished_program_projects_task() -> int:
    updated_count = publish_finished_program_projects()
    logger.info("Published %s program projects after finish", updated_count)
    return updated_count


@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_organizer_invitation(invitation_id, token):
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.utils import timezone
    from partner_programs.models import OrganizerInvitation
    from project_rates.workspace import digest

    rows = OrganizerInvitation.objects.filter(
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
        + "/organizer-invitation/"
        + token,
        "expires_at": invitation.expires_at,
        "logo_url": "https://786505.selcdn.ru/app_files/procollab_logo.png",
    }
    try:
        message = EmailMultiAlternatives(
            "Приглашение организатора | PROCOLLAB",
            render_to_string("email/organizer_invitation.txt", context),
            settings.EMAIL_USER,
            [invitation.email],
        )
        message.attach_alternative(
            render_to_string("email/organizer_invitation.html", context), "text/html"
        )
        if not message.send():
            raise RuntimeError("Invitation delivery did not complete")
        rows.update(delivery_status="sent")
    except Exception:
        rows.update(delivery_status="failed")
        raise

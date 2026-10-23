import logging

from procollab.celery import app
from partner_programs.services import publish_finished_program_projects

logger = logging.getLogger(__name__)


@app.task
def dispatch_program_certificates():
    from partner_programs.services.certificates import dispatch

    return dispatch()


@app.task
def process_program_certificate(certificate_id):
    from partner_programs.services.certificates import process

    return process(certificate_id)


@app.task
def send_test_program_certificate(program_id, user_id, snapshot):
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from partner_programs.models import PartnerProgram
    from partner_programs.certificate_models import (
        ProgramCertificate,
        ProgramCertificateBatch,
    )
    from partner_programs.services.certificates import (
        render_pdf,
        send_certificate,
        assets_for,
    )
    from partner_programs.services.management import person_name

    program = PartnerProgram.objects.get(pk=program_id)
    user = get_user_model().objects.get(pk=user_id)
    batch = ProgramCertificateBatch(program=program, snapshot=snapshot)
    row = ProgramCertificate(
        program=program,
        user=user,
        batch=batch,
        name=person_name(user),
        email=user.email,
        created_at=timezone.now(),
    )
    row.pdf = render_pdf(
        snapshot,
        assets_for(program, snapshot),
        row.name,
        program.name,
        "ПРОБНЫЙ",
        row.created_at,
    )
    send_certificate(row, test=True)


@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_registration_connection_notification(notification_id):
    from partner_programs.services.registration_notifications import deliver_notification

    deliver_notification(notification_id)


@app.task
def dispatch_registration_connection_notifications():
    from partner_programs.services.registration_notifications import (
        dispatch_pending_notifications,
    )

    return dispatch_pending_notifications()


@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_program_registration_confirmation(pending_id, generation):
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from urllib.parse import urlencode
    from partner_programs.models import PendingProgramRegistration
    from partner_programs.services.native_registration import (
        confirmation_token,
        frontend_url,
    )

    rows = PendingProgramRegistration.objects.filter(
        pk=pending_id, generation=generation, confirmed_at__isnull=True
    )
    pending = rows.select_related("program", "user").first()
    if not pending:
        return
    context = {
        "program_name": pending.program.name,
        "first_name": pending.user.first_name,
        "confirmation_url": f"{frontend_url()}/program-registration/{pending.program_id}#"
        + urlencode({"confirmation": confirmation_token(pending)}),
    }
    try:
        message = EmailMultiAlternatives(
            "Подтвердите регистрацию в программе | PROCOLLAB",
            render_to_string("email/program_registration.txt", context),
            settings.EMAIL_USER,
            [pending.user.email],
        )
        message.attach_alternative(
            render_to_string("email/program_registration.html", context), "text/html"
        )
        if not message.send():
            raise RuntimeError("Email delivery did not complete")
        rows.update(delivery_status="sent")
    except Exception:
        rows.update(delivery_status="failed")
        raise


@app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_attention_reminder(notification_id):
    from partner_programs.services.attention_actions import deliver_reminder

    deliver_reminder(notification_id)


@app.task
def dispatch_attention_reminders(batch_id=None):
    from partner_programs.services.attention_actions import dispatch_pending_reminders

    return dispatch_pending_reminders(batch_id)


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

import logging
from datetime import timedelta

from django.utils import timezone

from mailing.models import MailingScenarioLog
from mailing.scenarios import RecipientRule, SCENARIOS, TriggerType
from mailing.utils import send_mass_mail_from_template
from partner_programs.selectors import (
    program_participants,
    program_participants_without_project,
    programs_with_submission_deadline_on,
)
from procollab.celery import app

logger = logging.getLogger(__name__)


def _get_programs_for_scenario(scenario, target_date):
    match scenario.trigger:
        case TriggerType.PROGRAM_SUBMISSION_DEADLINE:
            return programs_with_submission_deadline_on(target_date)
        case _:
            raise ValueError(f"Unsupported trigger: {scenario.trigger}")


def _get_recipients(scenario, program_id: int):
    match scenario.recipient_rule:
        case RecipientRule.ALL_PARTICIPANTS:
            return program_participants(program_id)
        case RecipientRule.NO_PROJECT_IN_PROGRAM:
            return program_participants_without_project(program_id)
        case _:
            raise ValueError(f"Unsupported recipient rule: {scenario.recipient_rule}")


def _deadline_date(program):
    deadline = program.datetime_project_submission_ends or program.datetime_registration_ends
    return timezone.localtime(deadline).date()


def _send_scenario_for_program(scenario, program, scheduled_for):
    recipients = _get_recipients(scenario, program.id)
    if not recipients.exists():
        return 0

    pending_or_sent_ids = MailingScenarioLog.objects.filter(
        scenario_code=scenario.code,
        program=program,
        scheduled_for=scheduled_for,
        status__in=[
            MailingScenarioLog.Status.PENDING,
            MailingScenarioLog.Status.SENT,
        ],
    ).values_list("user_id", flat=True)

    recipients_to_send = recipients.exclude(id__in=pending_or_sent_ids)
    user_ids = list(recipients_to_send.values_list("id", flat=True))
    if not user_ids:
        return 0

    MailingScenarioLog.objects.filter(
        scenario_code=scenario.code,
        program=program,
        scheduled_for=scheduled_for,
        status=MailingScenarioLog.Status.FAILED,
        user_id__in=user_ids,
    ).update(status=MailingScenarioLog.Status.PENDING, error="", sent_at=None)

    logs = [
        MailingScenarioLog(
            scenario_code=scenario.code,
            program=program,
            user_id=user_id,
            scheduled_for=scheduled_for,
            status=MailingScenarioLog.Status.PENDING,
        )
        for user_id in user_ids
    ]
    MailingScenarioLog.objects.bulk_create(logs, ignore_conflicts=True)

    deadline_date = _deadline_date(program)

    def context_builder(user):
        return scenario.context_builder(program, user, deadline_date)

    def status_callback(user, msg):
        status = getattr(msg, "anymail_status", None)
        message_id = getattr(status, "message_id", None) if status else None
        if message_id:
            logger.info(
                "Scenario %s user=%s anymail_id=%s status=%s",
                scenario.code,
                user.id,
                message_id,
                getattr(status, "status", None),
            )
        else:
            logger.info(
                "Scenario %s user=%s anymail_status missing",
                scenario.code,
                user.id,
            )

    try:
        send_mass_mail_from_template(
            recipients_to_send,
            scenario.subject,
            scenario.template_name,
            context_builder=context_builder,
            status_callback=status_callback,
        )
    except Exception as exc:
        MailingScenarioLog.objects.filter(
            scenario_code=scenario.code,
            program=program,
            scheduled_for=scheduled_for,
            status=MailingScenarioLog.Status.PENDING,
            user_id__in=user_ids,
        ).update(status=MailingScenarioLog.Status.FAILED, error=str(exc))
        logger.exception(
            "Scenario %s failed for program %s", scenario.code, program.id
        )
        return 0

    MailingScenarioLog.objects.filter(
        scenario_code=scenario.code,
        program=program,
        scheduled_for=scheduled_for,
        status=MailingScenarioLog.Status.PENDING,
        user_id__in=user_ids,
    ).update(
        status=MailingScenarioLog.Status.SENT, sent_at=timezone.now(), error=""
    )
    return len(user_ids)


@app.task
def run_program_mailings() -> int:
    today = timezone.localdate()
    total_sent = 0
    for scenario in SCENARIOS:
        target_date = today + timedelta(days=scenario.offset_days)
        programs = _get_programs_for_scenario(scenario, target_date)
        for program in programs:
            total_sent += _send_scenario_for_program(scenario, program, today)
    logger.info("Program mailings sent: %s", total_sent)
    return total_sent

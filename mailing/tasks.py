import logging
from datetime import timedelta

from django.utils import timezone

from mailing.constants import FAILED_ANYMAIL_STATUSES
from mailing.models import MailingScenarioLog
from mailing.scenarios import RecipientRule, SCENARIOS, TriggerType
from mailing.utils import send_mass_mail_from_template
from partner_programs.selectors import (
    program_participants,
    program_participants_with_inactive_account,
    program_participants_with_inactive_account_registered_on,
    program_participants_with_unsubmitted_project,
    program_participants_without_project_registered_on,
    program_participants_without_project,
    programs_with_registration_end_on,
    programs_with_registrations_on,
    programs_with_submission_deadline_on,
)
from procollab.celery import app

logger = logging.getLogger(__name__)


def _get_programs_for_scenario(scenario, target_date):
    match scenario.trigger:
        case TriggerType.PROGRAM_SUBMISSION_DEADLINE:
            return programs_with_submission_deadline_on(target_date)
        case TriggerType.PROGRAM_REGISTRATION_DATE:
            return programs_with_registrations_on(target_date)
        case TriggerType.PROGRAM_REGISTRATION_END:
            return programs_with_registration_end_on(target_date)
        case _:
            raise ValueError(f"Unsupported trigger: {scenario.trigger}")


def _get_recipients(scenario, program, target_date):
    match scenario.recipient_rule:
        case RecipientRule.ALL_PARTICIPANTS:
            return program_participants(program.id)
        case RecipientRule.NO_PROJECT_IN_PROGRAM:
            return program_participants_without_project(program.id)
        case RecipientRule.NO_PROJECT_IN_PROGRAM_REGISTERED_ON_DATE:
            return program_participants_without_project_registered_on(
                program.id, target_date
            )
        case RecipientRule.PROJECT_NOT_SUBMITTED:
            return program_participants_with_unsubmitted_project(program.id)
        case RecipientRule.INACTIVE_ACCOUNT_IN_PROGRAM:
            return program_participants_with_inactive_account(
                program.id, program.datetime_started
            )
        case RecipientRule.INACTIVE_ACCOUNT_IN_PROGRAM_REGISTERED_ON_DATE:
            return program_participants_with_inactive_account_registered_on(
                program.id,
                target_date,
                program.datetime_started,
            )
        case _:
            raise ValueError(f"Unsupported recipient rule: {scenario.recipient_rule}")


def _deadline_date(program):
    deadline = program.datetime_project_submission_ends or program.datetime_registration_ends
    return timezone.localtime(deadline).date()


def _send_scenario_for_program(scenario, program, scheduled_for, target_date):
    recipients = _get_recipients(scenario, program, target_date)
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

    recipients_to_send = list(recipients.exclude(id__in=pending_or_sent_ids))
    user_ids = [user.id for user in recipients_to_send]
    if not user_ids:
        return 0

    logger.info(
        "Scenario %s program=%s scheduled_for=%s recipients=%s",
        scenario.code,
        program.id,
        scheduled_for,
        len(user_ids),
    )

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

    reference_date = (
        _deadline_date(program)
        if scenario.trigger == TriggerType.PROGRAM_SUBMISSION_DEADLINE
        else target_date
    )

    def context_builder(user):
        return scenario.context_builder(program, user, reference_date)

    sent_count = 0
    failed_count = 0

    def _normalize_status(status_value):
        if status_value is None:
            return set()
        if isinstance(status_value, dict):
            statuses = set()
            for value in status_value.values():
                if isinstance(value, (set, list, tuple)):
                    statuses.update(str(item) for item in value)
                else:
                    statuses.add(str(value))
            return {status.lower() for status in statuses}
        if isinstance(status_value, (set, list, tuple)):
            return {str(item).lower() for item in status_value}
        return {str(status_value).lower()}

    def status_callback(user, msg):
        nonlocal sent_count, failed_count
        status = getattr(msg, "anymail_status", None)
        message_id = getattr(status, "message_id", None) if status else None
        status_set = _normalize_status(getattr(status, "status", None))
        status_str = ",".join(sorted(status_set)) if status_set else "unknown"
        is_failed = not status_set or bool(status_set & FAILED_ANYMAIL_STATUSES)

        if not message_id:
            failed_count += 1
            MailingScenarioLog.objects.filter(
                scenario_code=scenario.code,
                program=program,
                scheduled_for=scheduled_for,
                status=MailingScenarioLog.Status.PENDING,
                user_id=user.id,
            ).update(
                status=MailingScenarioLog.Status.FAILED,
                error="anymail_status missing",
            )
            logger.warning(
                "Scenario %s user=%s anymail_status missing",
                scenario.code,
                user.id,
            )
            return

        if is_failed:
            failed_count += 1
            MailingScenarioLog.objects.filter(
                scenario_code=scenario.code,
                program=program,
                scheduled_for=scheduled_for,
                status=MailingScenarioLog.Status.PENDING,
                user_id=user.id,
            ).update(
                status=MailingScenarioLog.Status.FAILED,
                error=f"anymail_status={status_str} anymail_id={message_id}",
            )
            logger.error(
                "Scenario %s user=%s anymail_id=%s status=%s",
                scenario.code,
                user.id,
                message_id,
                status_str,
            )
            return

        sent_count += 1
        MailingScenarioLog.objects.filter(
            scenario_code=scenario.code,
            program=program,
            scheduled_for=scheduled_for,
            status=MailingScenarioLog.Status.PENDING,
            user_id=user.id,
        ).update(
            status=MailingScenarioLog.Status.SENT,
            sent_at=timezone.now(),
            error="",
        )
        logger.info(
            "Scenario %s user=%s anymail_id=%s status=%s",
            scenario.code,
            user.id,
            message_id,
            status_str,
        )

    try:
        num_sent = send_mass_mail_from_template(
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

    pending_qs = MailingScenarioLog.objects.filter(
        scenario_code=scenario.code,
        program=program,
        scheduled_for=scheduled_for,
        status=MailingScenarioLog.Status.PENDING,
        user_id__in=user_ids,
    )
    pending_count = pending_qs.count()
    if pending_count:
        pending_qs.update(
            status=MailingScenarioLog.Status.FAILED,
            error="anymail_status missing",
        )
        failed_count += pending_count
        logger.warning(
            "Scenario %s program=%s pending left after send: %s",
            scenario.code,
            program.id,
            pending_count,
        )

    logger.info(
        "Scenario %s program=%s send_messages=%s sent=%s failed=%s",
        scenario.code,
        program.id,
        num_sent,
        sent_count,
        failed_count,
    )
    return sent_count


@app.task
def run_program_mailings() -> int:
    today = timezone.localdate()
    total_sent = 0
    for scenario in SCENARIOS:
        if scenario.trigger == TriggerType.PROGRAM_SUBMISSION_DEADLINE:
            target_date = today + timedelta(days=scenario.offset_days)
        else:
            target_date = today - timedelta(days=scenario.offset_days)
        programs = _get_programs_for_scenario(scenario, target_date)
        for program in programs:
            total_sent += _send_scenario_for_program(
                scenario, program, today, target_date
            )
    logger.info("Program mailings sent: %s", total_sent)
    return total_sent

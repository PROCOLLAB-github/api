import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import send_mail
from django.utils import timezone

from procollab.celery import app
from partner_programs.models import PartnerProgram
from partner_programs.services import READINESS_LABELS, publish_finished_program_projects

logger = logging.getLogger(__name__)
REMINDER_DAYS = (14, 7, 3)
REMINDER_TEMPLATE = """\
Здравствуйте!

До старта кейс-чемпионата "{program_name}" осталось {days_left} {days_word}.

Незакрытые задачи:
{tasks_list}

Перейдите к редактированию чемпионата, чтобы дозаполнить параметры:
{edit_url}

Команда PROCOLLAB
"""


@app.task
def publish_finished_program_projects_task() -> int:
    updated_count = publish_finished_program_projects()
    logger.info("Published %s program projects after finish", updated_count)
    return updated_count


@app.task(name="partner_programs.tasks.send_readiness_reminders")
def send_readiness_reminders() -> str:
    now = timezone.now()
    sent_count = 0

    for days_left in REMINDER_DAYS:
        target_date = now + timedelta(days=days_left)
        programs = PartnerProgram.objects.filter(
            status=PartnerProgram.STATUS_PUBLISHED,
            datetime_started__gte=target_date - timedelta(hours=12),
            datetime_started__lt=target_date + timedelta(hours=12),
        ).prefetch_related("managers")

        for program in programs:
            reminder_key = f"days_{days_left}"
            sent_reminders = list(program.sent_reminders or [])
            if reminder_key in sent_reminders:
                continue

            checklist = program.calculate_readiness()
            unfinished_tasks = [key for key, done in checklist.items() if not done]
            if not unfinished_tasks:
                continue

            program_sent_count = _send_program_reminders(
                program=program,
                days_left=days_left,
                unfinished_tasks=unfinished_tasks,
            )
            if program_sent_count == 0:
                continue

            sent_count += program_sent_count
            sent_reminders.append(reminder_key)
            program.sent_reminders = sent_reminders
            program.save(update_fields=["sent_reminders"])

    return f"Readiness reminders sent: {sent_count}"


def _send_program_reminders(
    program: PartnerProgram,
    days_left: int,
    unfinished_tasks: list[str],
) -> int:
    sent_count = 0
    tasks_list = "\n".join(
        f"  - {_format_task_name(task_key)}" for task_key in unfinished_tasks
    )
    edit_url = f"{settings.FRONTEND_URL}/office/program/{program.id}/edit"

    for manager in program.managers.all():
        if not _email_reminders_enabled(manager):
            continue

        sent_count += send_mail(
            subject=f"До старта чемпионата \"{program.name}\" {days_left} {_pluralize_days(days_left)}",
            message=REMINDER_TEMPLATE.format(
                program_name=program.name,
                days_left=days_left,
                days_word=_pluralize_days(days_left),
                tasks_list=tasks_list,
                edit_url=edit_url,
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[manager.email],
            fail_silently=True,
        )

    return sent_count


def _email_reminders_enabled(user) -> bool:
    try:
        return user.notification_preferences.email_reminders_enabled
    except ObjectDoesNotExist:
        return False


def _format_task_name(task_key: str) -> str:
    return READINESS_LABELS.get(task_key, task_key)


def _pluralize_days(days_left: int) -> str:
    if 11 <= days_left % 100 <= 14:
        return "дней"
    if days_left % 10 == 1:
        return "день"
    if 2 <= days_left % 10 <= 4:
        return "дня"
    return "дней"

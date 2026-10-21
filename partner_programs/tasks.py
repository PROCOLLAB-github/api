import logging

from procollab.celery import app
from partner_programs.services import publish_finished_program_projects

logger = logging.getLogger(__name__)


@app.task
def publish_finished_program_projects_task() -> int:
    updated_count = publish_finished_program_projects()
    logger.info("Published %s program projects after finish", updated_count)
    return updated_count


@app.task
def send_attention_reminder(pk):
    from partner_programs.services.attention_actions import deliver_reminder

    deliver_reminder(pk)


@app.task
def dispatch_attention_reminders(batch_id=None):
    from partner_programs.services.attention_actions import dispatch_pending_reminders

    return dispatch_pending_reminders(batch_id)

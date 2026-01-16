import logging

from procollab.celery import app
from partner_programs.services import publish_finished_program_projects

logger = logging.getLogger(__name__)


@app.task
def publish_finished_program_projects_task() -> int:
    updated_count = publish_finished_program_projects()
    logger.info("Published %s program projects after finish", updated_count)
    return updated_count

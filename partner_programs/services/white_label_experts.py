"""Экспертное членство организаторов только в настроенной программе пилота."""

from django.conf import settings
from django.db import transaction

from partner_programs.models import PartnerProgram
from procollab.white_label import get_config
from project_rates.models import ExpertCaseScope
from users.models import Expert


def organizer_expert_program_id():
    if not getattr(settings, "WHITE_LABEL_ORGANIZERS_ARE_EXPERTS", False):
        return None
    config = get_config()
    return config.program_id if config.enabled else None


@transaction.atomic
def ensure_organizer_experts(program_id):
    """Повторяемая подготовка без писем, назначения проектов и смены роли пользователя."""
    if program_id != organizer_expert_program_id():
        return 0
    program = PartnerProgram.objects.select_for_update().get(pk=program_id)
    added = 0
    for user in program.managers.filter(is_active=True).order_by("pk"):
        expert, _ = Expert.objects.get_or_create(user=user)
        if not expert.programs.filter(pk=program.pk).exists():
            expert.programs.add(program)
            added += 1
        # Имеющийся ограниченный набор кейсов остается без изменений.
        ExpertCaseScope.objects.get_or_create(partner_program=program, expert=expert)
    return added

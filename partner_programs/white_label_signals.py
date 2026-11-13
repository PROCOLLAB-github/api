"""Одинаковое членство экспертов при добавлении организатора через API и admin."""

from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from partner_programs.models import PartnerProgram
from partner_programs.services.white_label_experts import (
    ensure_organizer_experts,
    organizer_expert_program_id,
)


@receiver(m2m_changed, sender=PartnerProgram.managers.through)
def ensure_white_label_experts(sender, instance, action, reverse, pk_set, **kwargs):
    if action != "post_add" or not pk_set:
        return
    program_id = organizer_expert_program_id()
    if program_id is not None and (
        program_id in pk_set if reverse else instance.pk == program_id
    ):
        ensure_organizer_experts(program_id)

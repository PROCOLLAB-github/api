from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from partner_programs.models import PartnerProgram
from users.models import Expert


@receiver(m2m_changed, sender=PartnerProgram.managers.through)
def ensure_organizer_expert_identity(
    sender, instance, action, reverse, pk_set, using, **kwargs
):
    if action != "post_add" or not pk_set:
        return
    user_ids = {instance.pk} if reverse else pk_set
    # Assignments need an Expert identity. The manager relation grants access;
    # Expert.programs remains the record of independently granted expertise.
    Expert.objects.using(using).bulk_create(
        [Expert(user_id=user_id) for user_id in sorted(user_ids)],
        ignore_conflicts=True,
    )

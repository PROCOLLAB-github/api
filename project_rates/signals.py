from django.db.models.signals import post_save
from django.dispatch import receiver

from partner_programs.models import PartnerProgram
from project_rates.models import Criteria


@receiver(post_save, sender=PartnerProgram)
def create_comment(sender, instance, created, **kwargs):
    Criteria.objects.get_or_create(
        name="Комментарий",
        description="Доп. поле для впечатлений о проекте",
        type="str",
        partner_program_id=instance.id,
    )

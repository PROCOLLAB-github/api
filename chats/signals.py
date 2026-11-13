from django.db.models.signals import post_save
from django.dispatch import receiver

from chats.models import ProgramChannel
from partner_programs.models import PartnerProgram


@receiver(post_save, sender=PartnerProgram)
def create_program_channel(sender, instance, created, raw, using, **kwargs):
    if created and not raw:
        ProgramChannel.objects.using(using).get_or_create(program=instance)

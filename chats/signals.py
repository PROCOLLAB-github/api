from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from chats.attachments import ATTACHMENT_IN_USE, used_by_visible_chat_message
from chats.models import ProgramChannel
from files.models import UserFile
from partner_programs.models import PartnerProgram


@receiver(post_save, sender=PartnerProgram)
def create_program_channel(sender, instance, created, raw, using, **kwargs):
    if created and not raw:
        ProgramChannel.objects.using(using).get_or_create(program=instance)


@receiver(pre_delete, sender=UserFile, dispatch_uid="protect_visible_chat_attachment")
def protect_visible_chat_attachment(sender, instance, using, **kwargs):
    sender.objects.using(using).select_for_update().filter(pk=instance.pk).first()
    if used_by_visible_chat_message(instance.pk, using=using):
        raise ProtectedError(ATTACHMENT_IN_USE, [instance])

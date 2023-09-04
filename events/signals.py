from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Event
from django.conf import settings
from events.constants import APP_URL
from events.helpers import send_message, edit_message


@receiver(post_save, sender=Event)
def autoposting_receiver(sender, instance, created, *args, **kwargs):
    if settings.AUTOPOSTING_ON:
        if created:
            link = f"{APP_URL}/{instance.pk}"
            text = f"***{instance.title}***\n{instance.short_text}\n\n{link}"
            response = send_message(text, settings.TELEGRAM_CHANNEL)
            if response["ok"]:
                instance.tg_message_id = response["result"]["message_id"]
                instance.save()
        else:
            link = f"{APP_URL}/{instance.pk}"
            text = f"***{instance.title}***\n{instance.short_text}\n\n{link}"
            response = edit_message(
                text, instance.tg_message_id, settings.TELEGRAM_CHANNEL
            )

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Event
import requests
from django.conf import settings


@receiver(post_save, sender=Event)
def my_callback(sender, instance, created, *args, **kwargs):
    if created:
        link = f"https://procollab.ru/events/{instance.pk}/"
        text = f"***{instance.title}***\n{instance.short_text}\n\n" + link
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": settings.TELEGRAM_CHANNEL,
            "text": text,
            "parse_mode": "markdown",
        }
        r = requests.post(url, data=data).json()
        if r["ok"]:
            instance.tg_message_id = r["result"]["message_id"]
            instance.save()
        # todo: logging
        # print(r)
    else:
        link = f"https://procollab.ru/events/{instance.pk}/"
        text = f"***{instance.title}***\n{instance.short_text}\n\n" + link
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/editMessageText"
        data = {
            "chat_id": settings.TELEGRAM_CHANNEL,
            "text": text,
            "parse_mode": "markdown",
            "message_id": instance.tg_message_id,
        }
        r = requests.post(url, data=data).json()
        # todo: logging

        # print(r)

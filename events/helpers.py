import requests
from events.constants import TELEGRAM_API_URL
from django.conf import settings


def send_message(text, chat_id):
    url = f"{TELEGRAM_API_URL}{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "markdown",
    }
    return requests.post(url, data=data).json()


def edit_message(text, message_id, chat_id):
    url = f"{TELEGRAM_API_URL}{settings.TELEGRAM_BOT_TOKEN}/editMessageText"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "markdown",
        "message_id": message_id,
    }
    return requests.post(url, data=data).json()

import requests
from events.constants import EDIT_MESSAGE_URL
from events.constants import SEND_MESSAGE_URL


def send_message(text, chat_id):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "markdown",
    }
    return requests.post(SEND_MESSAGE_URL, data=data).json()


def edit_message(text, message_id, chat_id):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "markdown",
        "message_id": message_id,
    }
    return requests.post(EDIT_MESSAGE_URL, data=data).json()

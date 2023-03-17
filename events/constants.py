from django.conf import settings


APP_URL = "https://procollab.ru/events"
EDIT_MESSAGE_URL = (
    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/editMessageText"
)
SEND_MESSAGE_URL = (
    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
)

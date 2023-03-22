APP_URL = "https://procollab.ru/events"
TELEGRAM_API_URL = "https://api.telegram.org/bot"

OFFLINE = 0
ONLINE = 1
ONLINE_OFFLINE = 2

VERBOSE_EVENT_TYPE = (
	(OFFLINE, "Оффлайн"),
	(ONLINE, "Онлайн"),
	(ONLINE_OFFLINE, "Оффлайн и онлайн")
)
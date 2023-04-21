from django.conf import settings

ADMIN = 0
MEMBER = 1
MENTOR = 2
EXPERT = 3
INVESTOR = 4

VERBOSE_USER_TYPES = (
    (MEMBER, "Участник"),
    (MENTOR, "Ментор"),
    (EXPERT, "Эксперт"),
    (INVESTOR, "Инвестор"),
)

VERBOSE_ROLE_TYPES = (
    (MENTOR, "Ментор"),
    (EXPERT, "Эксперт"),
    (INVESTOR, "Инвестор"),
)

VERIFY_EMAIL_REDIRECT_URL = "https://app.procollab.ru/auth/verification/"

PROTOCOL = "https"
if settings.DEBUG:
    PROTOCOL = "http"

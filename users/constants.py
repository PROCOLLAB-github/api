from enum import Enum

from django.conf import settings


class OnboardingStage(Enum):
    intro = 0
    skills = 1
    account_type = 2
    completed = None


ADMIN = 0
MEMBER = 1
MENTOR = 2
EXPERT = 3
INVESTOR = 4

VERBOSE_USER_TYPES = (
    (MEMBER, "Участник"),
    (MENTOR, "Ментор"),
    (EXPERT, "Консультант"),
    (INVESTOR, "Инвестор"),
)

VERBOSE_ROLE_TYPES = (
    (MENTOR, "Ментор"),
    (EXPERT, "Консультант"),
    (INVESTOR, "Инвестор"),
)

VERIFY_EMAIL_REDIRECT_URL = "https://app.procollab.ru/auth/verification/"


PROTOCOL = "https"
if settings.DEBUG:
    PROTOCOL = "http"

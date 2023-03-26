from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse

from core.utils import Email

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

REDIRECT_URL = "https://app.procollab.ru/auth/verification/"

PROTOCOL = "https"

if settings.DEBUG:
    PROTOCOL = "https"


def reset_email(user, request):
    access_token = RefreshToken.for_user(user).access_token
    refresh_token = RefreshToken.for_user(user)

    relative_link = reverse("users:password_reset_sent")

    current_site = get_current_site(request).domain
    absolute_url = (
        f"{PROTOCOL}://{current_site}{relative_link}?"
        f"access_token={access_token}&refresh_token={refresh_token}"
    )

    email_body = (
        f"Здравствуйте, {user.first_name} {user.last_name}!"
        f" Перейдите по данной ссылке для смены пароля:\n {absolute_url}\n\nС уважением, "
        f"Procollab!"
    )

    data = {
        "email_body": email_body,
        "email_subject": "Procollab | Сброс пароля",
        "to_email": user.email,
    }

    Email.send_email(data)


def verify_email(user, request):
    token = RefreshToken.for_user(user).access_token

    relative_link = reverse("users:account_email_verification_sent")
    current_site = get_current_site(request).domain

    absolute_url = f"{PROTOCOL}://{current_site}{relative_link}?token={token}"

    email_body = (
        f"Подтверждение адреса электронной почты"
        f"\n\n"
        f"Здравствйте, {user.first_name} {user.last_name}!"
        f"\n"
        f"Ваш адрес электронной почты был "
        f"связан с созданием Procollab аккаунта. "
        f"Для подтверждения адреса перейдите по ссылке:\n{absolute_url}"
        f"\n\n"
        f"Если данное сообщение пришло вам по ошибке, проигнорируйте его."
        f"\n"
        f"С уважением, команда Procollab!"
    )

    data = {
        "email_body": email_body,
        "email_subject": "Procollab | Подтверждение почты",
        "to_email": user.email,
    }

    Email.send_email(data)

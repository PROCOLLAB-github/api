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


def reset_email(user, request):
    access_token = RefreshToken.for_user(user).access_token
    refresh_token = RefreshToken.for_user(user)

    relative_link = reverse("users:password_reset_sent")

    current_site = get_current_site(request).domain
    absolute_url = f"https://{current_site}{relative_link}?access_token={access_token}&refresh_token={refresh_token}"

    email_body = f"Hi, {user.first_name} {user.last_name}! Use link below for reset password {absolute_url}"

    data = {
        "email_body": email_body,
        "email_subject": "Reset password",
        "to_email": user.email,
    }

    Email.send_email(data)


def verify_email(user, request):
    token = RefreshToken.for_user(user).access_token

    relative_link = reverse("users:account_email_verification_sent")
    current_site = get_current_site(request).domain
    absolute_url = f"https://{current_site}{relative_link}?token={token}"

    email_body = f"Hi, {user.first_name} {user.last_name}! Use link below verify your email {absolute_url}"

    data = {
        "email_body": email_body,
        "email_subject": "Verify your email",
        "to_email": user.email,
    }

    Email.send_email(data)

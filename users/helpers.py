from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse

from users.constants import PROTOCOL
from users.models import UserAchievement, UserLink

User = get_user_model()


def verify_email(user, request):
    token = RefreshToken.for_user(user).access_token

    relative_link = reverse("users:account_email_verification_sent")
    current_site = get_current_site(request).domain

    absolute_url = f"{PROTOCOL}://{current_site}{relative_link}?token={token}"

    context = {
        "absolute_url": absolute_url,
    }
    email_html_message = render_to_string("email/confirm-email.html", context)
    email_plaintext_message = render_to_string("email/confirm-email.txt", context)

    msg = EmailMultiAlternatives(
        "Подтверждение почты | Procollab",
        email_plaintext_message,
        "procollab2022@gmail.com",
        [user.email],
    )
    msg.attach_alternative(email_html_message, "text/html")
    msg.send()


def send_verification_completed_email(user: User):
    context = {}
    email_html_message = render_to_string("email/verification-succeed.html", context)
    email_plaintext_message = render_to_string("email/verification-succeed.txt", context)

    msg = EmailMultiAlternatives(
        "Аккаунт подтвержден | Procollab",
        email_plaintext_message,
        "procollab2022@gmail.com",
        [user.email],
    )
    msg.attach_alternative(email_html_message, "text/html")
    msg.send()


def check_related_fields_update(data, pk):
    """
    Check if achievements or links were updated and update them.
    """

    if data.get("achievements") is not None:
        update_achievements(data.get("achievements"), pk)

    if data.get("links") is not None:
        update_links(data.get("links"), pk)


def update_achievements(achievements, pk):
    """
    Bootleg version of updating achievements via user
    """

    # delete all old achievements
    UserAchievement.objects.filter(user_id=pk).delete()
    # create new achievements
    UserAchievement.objects.bulk_create(
        [
            UserAchievement(
                user_id=pk,
                title=achievement.get("title"),
                status=achievement.get("status"),
            )
            for achievement in achievements
        ]
    )


def update_links(links, pk):
    """
    Bootleg version of updating links via user
    """

    # delete all old links
    UserLink.objects.filter(user_id=pk).delete()
    # create new links
    UserLink.objects.bulk_create(
        [
            UserLink(
                user_id=pk,
                link=link,
            )
            for link in links
        ]
    )

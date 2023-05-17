import os

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse

from core.utils import Email
from users.constants import PROTOCOL
from users.models import UserAchievement, UserLink

User = get_user_model()


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


def send_verification_completed_email(user: User):
    fname = os.path.join(settings.STATIC_ROOT, "verification-succeed.html")
    with open(fname, "r", encoding="utf-8") as f:
        html_content = f.read()
        email_body = (
            f"Поздравляю тебя, {user.first_name} {user.last_name}! Ты прошел верификацию и"
            f" стал частью сообщества PROCOLLAB!"
            f"Теперь ты сможешь пользоваться всем функционалом платформы, создавать проекты,"
            f" искать команду, находить нужные мероприятия."
            f"Следи за анонсами обновлений в нашей группе в ВК https://vk.com/PROCOLLAB "
            f"И скорее переходи на саму платформу, чтобы уже сегодня начать создавать свой проект."
            f"https://procollab.ru "
            f"С уважением, "
            f"Администрация PROCOLLAB"
        )

        data = {
            "email_body": email_body,
            "email_subject": "Procollab | Верификация",
            "to_email": user.email,
            "html_content": html_content,
        }

        Email.send_email(data)


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

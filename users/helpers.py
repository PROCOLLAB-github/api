from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse

from mailing.utils import send_mail
from users.constants import PROTOCOL
from users.models import UserAchievement, UserLink

User = get_user_model()


def verify_email(user, request):
    token = RefreshToken.for_user(user).access_token
    relative_link = reverse("users:account_email_verification_sent")
    current_site = get_current_site(request).domain
    absolute_url = f"{PROTOCOL}://{current_site}{relative_link}?token={token}"
    template_content = open(
        settings.BASE_DIR / "templates/email/confirm-email.html", encoding="utf-8"
    ).read()
    send_mail(
        user=user,
        subject="Procollab | Подтверждение почты",
        template_string=template_content,
        template_context={"absolute_url": absolute_url},
    )


def send_verification_completed_email(user: User):
    template_content = open(
        settings.BASE_DIR / "templates/email/verification-succeed.html", encoding="utf-8"
    ).read()
    send_mail(
        user=user,
        subject="Procollab | Верификация",
        template_string=template_content,
    )


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


def force_verify_user(user: User) -> None:
    if user.is_active:
        return

    # todo: send email
    user.is_active = True
    user.save()


def check_chache_for_cv(cache_key: str, cooldown_time: int) -> int | None:
    cached_timestamp = cache.get(cache_key)
    if cached_timestamp:
        time_passed = timezone.now() - cached_timestamp
        remaining_time = cooldown_time - int(time_passed.total_seconds())
        return remaining_time

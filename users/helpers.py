from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.core.cache import cache
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import now
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from files.models import UserFile
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
        settings.BASE_DIR / "templates/email/verification-succeed.html",
        encoding="utf-8",
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


def _extract_file_links(raw_files) -> list[str]:
    """
    Normalize file input payload into a list of links.
    Accepts either a list of strings or a list of dicts with a `link` key.
    """

    if not raw_files:
        return []

    if isinstance(raw_files, str):
        raw_files = [raw_files]

    if not isinstance(raw_files, (list, tuple)):
        return []

    links: list[str] = []
    for item in raw_files:
        if isinstance(item, str):
            links.append(item)
        elif isinstance(item, dict):
            link = item.get("link")
            if isinstance(link, str):
                links.append(link)
    # keep original order but remove empties/duplicates
    seen = set()
    deduped = []
    for link in links:
        if link and link not in seen:
            seen.add(link)
            deduped.append(link)
    return deduped


def _resolve_user_files(file_links: list[str], user_id: int) -> list[UserFile]:
    """
    Resolve file links to UserFile objects, validating ownership.
    """

    if not file_links:
        return []

    files = UserFile.objects.filter(link__in=file_links)
    files_by_link = {f.link: f for f in files}

    missing = [link for link in file_links if link not in files_by_link]
    if missing:
        raise ValidationError({"achievements": [f"Файлы не найдены: {missing}"]})

    wrong_owner = [
        link
        for link, file in files_by_link.items()
        if file.user_id is None or file.user_id != user_id
    ]
    if wrong_owner:
        raise ValidationError(
            {
                "achievements": [
                    "Нельзя привязать файлы: нет владельца или владелец другой "
                    f"({wrong_owner})"
                ]
            }
        )

    # Preserve original ordering
    return [files_by_link[link] for link in file_links]


@transaction.atomic
def update_achievements(achievements, pk):
    """
    Bootleg version of updating achievements via user
    """

    if achievements is None:
        return

    if not isinstance(achievements, list):
        raise ValidationError({"achievements": ["Должен быть списком объектов."]})

    existing_achievements = {
        achievement.id: achievement
        for achievement in UserAchievement.objects.filter(user_id=pk)
    }
    seen_ids: set[int] = set()

    for achievement_payload in achievements:
        if not isinstance(achievement_payload, dict):
            raise ValidationError({"achievements": ["Каждое достижение должно быть объектом."]})

        achievement_id = achievement_payload.get("id")
        has_year_key = "year" in achievement_payload
        raw_files = None
        files_key_present = False

        if "file_links" in achievement_payload:
            raw_files = achievement_payload.get("file_links")
            files_key_present = True
        elif "files" in achievement_payload:
            raw_files = achievement_payload.get("files")
            files_key_present = True

        file_links = (
            _extract_file_links(raw_files) if files_key_present else None
        )

        if achievement_id and achievement_id in existing_achievements:
            achievement_instance = existing_achievements[achievement_id]
            title = achievement_payload.get("title")
            status = achievement_payload.get("status")

            if title is not None:
                achievement_instance.title = title
            if status is not None:
                achievement_instance.status = status
            if has_year_key:
                achievement_instance.year = achievement_payload.get("year")
            achievement_instance.save()
        else:
            achievement_instance = UserAchievement.objects.create(
                user_id=pk,
                title=achievement_payload.get("title"),
                status=achievement_payload.get("status"),
                year=achievement_payload.get("year"),
            )

        seen_ids.add(achievement_instance.id)

        if file_links is not None:
            user_files = _resolve_user_files(file_links, pk)
            achievement_instance.files.set(user_files)

    stale_ids = set(existing_achievements.keys()) - seen_ids
    if stale_ids:
        UserAchievement.objects.filter(id__in=stale_ids).delete()


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
    if hasattr(user, "verification_date"):
        user.verification_date = now().date()
    user.save()


def check_chache_for_cv(cache_key: str, cooldown_time: int) -> int | None:
    cached_timestamp = cache.get(cache_key)
    if cached_timestamp:
        time_passed = timezone.now() - cached_timestamp
        remaining_time = cooldown_time - int(time_passed.total_seconds())
        return remaining_time

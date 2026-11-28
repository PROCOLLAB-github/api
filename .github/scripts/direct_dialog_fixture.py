"""Create or remove exactly two synthetic users for the live DEV chat smoke."""

import json
import os
import re
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken  # noqa: E402

from chats.models import DirectChat, DirectChatSpamReport  # noqa: E402
from files.models import UserFile  # noqa: E402
from files.service import SelectelSwiftStorage, is_storage_url  # noqa: E402

key = os.environ["DIRECT_DIALOG_QA_KEY"]
action = os.environ["DIRECT_DIALOG_QA_ACTION"]
selected_ids = [int(part) for part in os.environ.get("DIRECT_DIALOG_QA_SELECTED", "").split(",") if part]
if not re.fullmatch(r"[a-f0-9]{24}", key) or action not in ("prepare", "cleanup", "prepare-storage"):
    raise SystemExit("Invalid direct chat acceptance arguments")

emails = [f"direct-qa-{key}-{index}@example.test" for index in (1, 2)]
users = get_user_model().objects
if action == "prepare-storage":
    base = urlsplit(settings.SELECTEL_SWIFT_URL)
    if base.hostname != "api.selcdn.ru" or base.scheme != "https":
        raise SystemExit("Unexpected storage endpoint")
    account = base.path.split("/")[2]
    if not re.fullmatch(r"SEL_[0-9]+", account):
        raise SystemExit("Unexpected storage account path")
    url = urlunsplit(("https", base.netloc, f"/v1/{account}/procollab-dev-direct-private", "", ""))
    headers = {"X-Auth-Token": SelectelSwiftStorage._get_auth_token()}
    response = requests.head(url, headers=headers, timeout=(5, 12), allow_redirects=False)
    create_status = None
    if response.status_code == 404:
        create_status = requests.put(
            url, headers={**headers, "X-Container-Meta-Type": "private"},
            timeout=(5, 12), allow_redirects=False,
        ).status_code
        response = requests.head(url, headers=headers, timeout=(5, 12), allow_redirects=False)
    print(json.dumps({
        "create_status": create_status,
        "head_status": response.status_code,
        "private": response.headers.get("X-Container-Meta-Type") == "private",
    }))
elif action == "prepare":
    with transaction.atomic():
        accounts = []
        for email, name in zip(emails, ("Илья", "Мария"), strict=True):
            user = users.create(
                email=email,
                first_name=name,
                last_name="Проверка чата",
                is_active=True,
                onboarding_stage=None,
                verification_notice_acknowledged_at=timezone.now(),
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])
            refresh = RefreshToken.for_user(user)
            refresh.set_exp(lifetime=timedelta(minutes=20))
            access = AccessToken.for_user(user)
            access.set_exp(lifetime=timedelta(minutes=15))
            accounts.append({"id": user.pk, "access": str(access), "refresh": str(refresh)})
        chat = DirectChat.get_chat(*(users.get(email=email) for email in emails))
    print(json.dumps({"origin": "https://dev.procollab.ru", "chat": chat.pk, "accounts": accounts}))
else:
    accounts = list(users.filter(email__in=emails, is_staff=False, is_superuser=False))
    if accounts:
        chats = DirectChat.objects.none()
        if len(accounts) == 2:
            chat_id = DirectChat.get_chat_id_from_users(*accounts)
            chats = DirectChat.objects.filter(pk=chat_id)
        saved_ids = set(DirectChatSpamReport.objects.filter(
            chat__in=chats, message_id__in=selected_ids, reporter__in=accounts
        ).values_list("message_id", flat=True))
        users.filter(pk__in=[user.pk for user in accounts]).update(is_active=False)
        failed = []
        headers = {"X-Auth-Token": SelectelSwiftStorage._get_auth_token()}
        for upload in UserFile.objects.filter(user__in=accounts):
            if not is_storage_url(upload.link):
                failed.append("unmanaged")
                continue
            try:
                response = requests.delete(upload.link, headers=headers, timeout=(5, 12), allow_redirects=False)
            except requests.RequestException:
                failed.append("transport")
                continue
            if not (200 <= response.status_code < 300 or response.status_code == 404):
                failed.append(response.status_code)
                continue
            upload.delete()
        with transaction.atomic():
            chats.delete()
            if not failed:
                users.filter(pk__in=[user.pk for user in accounts]).delete()
        print(json.dumps({
            "cleaned": 0 if failed else len(accounts),
            "deactivated": len(accounts),
            "selected_reports_saved": len(saved_ids),
            "storage_failures": failed,
        }))

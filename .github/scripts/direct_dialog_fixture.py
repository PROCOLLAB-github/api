"""Create or remove exactly two synthetic users for the live DEV chat smoke."""

import json
import os
import re
from datetime import timedelta

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken  # noqa: E402

from chats.models import DirectChat, DirectChatSpamReport  # noqa: E402
from files.models import UserFile  # noqa: E402
from files.service import SelectelSwiftStorage  # noqa: E402

key = os.environ["DIRECT_DIALOG_QA_KEY"]
action = os.environ["DIRECT_DIALOG_QA_ACTION"]
selected_ids = [int(part) for part in os.environ.get("DIRECT_DIALOG_QA_SELECTED", "").split(",") if part]
if not re.fullmatch(r"[a-f0-9]{24}", key) or action not in ("prepare", "cleanup"):
    raise SystemExit("Invalid direct chat acceptance arguments")

emails = [f"direct-qa-{key}-{index}@example.test" for index in (1, 2)]
users = get_user_model().objects
if action == "prepare":
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
        storage = SelectelSwiftStorage()
        for upload in UserFile.objects.filter(user__in=accounts):
            storage.delete(upload.link)
            upload.delete()
        with transaction.atomic():
            chats.delete()
            users.filter(pk__in=[user.pk for user in accounts]).delete()
        print(json.dumps({"cleaned": len(accounts), "selected_reports_saved": len(saved_ids)}))

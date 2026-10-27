"""Однократная согласованная выдача права создания программ для приемки на DEV."""

import os
import sys


def main():
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission
    from django.db import transaction

    assert settings.EXPERT_WORKSPACE_FRONTEND_URL.rstrip("/") == "https://dev.procollab.ru"
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=11)
        assert user.is_active
        assert user.first_name == "Иван" and user.last_name == "Токарев"
        permission = Permission.objects.get(
            content_type__app_label="partner_programs",
            content_type__model="partnerprogram",
            codename="add_partnerprogram",
        )
        already_allowed = user.has_perm("partner_programs.add_partnerprogram")
        if not already_allowed:
            user.user_permissions.add(permission)
    user = get_user_model().objects.get(pk=11)
    assert user.has_perm("partner_programs.add_partnerprogram")
    print(
        {
            "user_id": user.pk,
            "permission": "partner_programs.add_partnerprogram",
            "already_allowed": already_allowed,
            "can_create_program": True,
        }
    )


if __name__ == "__main__":
    main()

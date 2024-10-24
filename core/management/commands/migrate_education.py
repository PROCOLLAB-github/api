import json

from django.db import transaction
from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from users.models import UserEducation


CustomUser = get_user_model()


class Command(BaseCommand):
    """
    Use: python manage.py migrate_education.
    """
    def handle(self, *args, **kwargs):
        self.stdout.write("Start manual migration ...")
        try:
            total_user_migrate = migrate_organization_to_education()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Manual migration complete, users migrated: {total_user_migrate}"
                )
            )
        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Migration failed: {str(e)}")
            )


@transaction.atomic
def migrate_organization_to_education() -> int:
    """
    Migrate old field `organization` to new model `Education`.
    Returns count migrated users.
    Stored migrated info into `BASE_DIR / "core" / "log" / "migrated_users.json"`
    """
    user_with_education_ids: list[int] = UserEducation.objects.values_list("user__id", flat=True)
    users_with_organization_without_education = (
        CustomUser.objects
        .exclude(organization=None)
        .exclude(organization="")
        .exclude(id__in=user_with_education_ids)
    )
    UserEducation.objects.bulk_create([
        UserEducation(
            user=user,
            organization_name=user.organization,
        )
        for user in users_with_organization_without_education
    ])

    data = [
        {"user_id": user.id, "user_organization_field": user.organization}
        for user in users_with_organization_without_education
    ]

    file_dump = settings.BASE_DIR / "core" / "log" / "migrated_users.json"
    with open(file_dump, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

    return users_with_organization_without_education.count()

from django.db import transaction
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
    """
    users_with_irganization = CustomUser.objects.exclude(organization=None).exclude(organization="")
    UserEducation.objects.bulk_create([
        UserEducation(
            user=user,
            organization_name=user.organization,
        )
        for user in users_with_irganization
    ])
    return users_with_irganization.count()

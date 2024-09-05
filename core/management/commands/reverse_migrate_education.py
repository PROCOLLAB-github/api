from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser

from users.models import UserEducation


CustomUser = get_user_model()


class Command(BaseCommand):
    """
    Use: python manage.py reverse_migrate_education.
    """

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm delete Users educations from UserEducation model"
        )

    def handle(self, *args, **kwargs):
        confirm = kwargs["confirm"]
        self.stdout.write(self.style.WARNING(
            "You are about to DELETE ALL INSTANCES in the UserEducation model."))

        if not confirm:
            answer = input("Type 'yes' to continue, or 'no' to cancel: ").lower()
            if answer != "yes":
                self.stdout.write(self.style.ERROR("Manual migrations canceled."))
                return

        self.stdout.write("Starting manual migrations...")

        try:
            deleted_instances = delete_all_instances_usereducation()
            self.stdout.write(self.style.SUCCESS("Manual migrations completed successfully."))
            self.stdout.write(self.style.SUCCESS(f"Deleted: {deleted_instances}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Manual migrations failed: {str(e)}"))


@transaction.atomic
def delete_all_instances_usereducation() -> int:
    """
    Destroy all UserEducation instances.
    """
    count = UserEducation.objects.count()
    UserEducation.objects.all().delete()
    return count

from django.db import transaction
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from core.models import SkillToObject

CustomUser = get_user_model()


class Command(BaseCommand):
    """
    DO NOT USE IN PROD, ONLY DEBUG.
    """
    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm executing the manual migrations.",
        )

    def handle(self, *args, **options):
        confirm = options["confirm"]

        if not confirm:
            self.stdout.write(self.style.WARNING("DO NOT USE IN PROD, ONLY DEBUG."))
            self.stdout.write(self.style.WARNING("DO NOT USE IN PROD, ONLY DEBUG."))
            self.stdout.write(self.style.WARNING("DO NOT USE IN PROD, ONLY DEBUG."))
            answer = input(
                "You are about to perform manual migrations. This command is for DEBUG use only. "
                "Are you sure you want to proceed?"
                "Type 'yes' to continue, or 'no' to cancel: "
            ).lower()
            if answer != "yes":
                self.stdout.write(self.style.ERROR("Manual migrations canceled."))
                return

        self.stdout.write("Starting manual migrations...")
        try:
            reverse()
            self.stdout.write(self.style.SUCCESS("Manual migrations completed successfully."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Manual migrations failed: {str(e)}"))


@transaction.atomic
def reverse():
    """Clear CustomUser fields `v2_speciality`, `skills` and `dataset_migration_applied` -> False"""
    for user in CustomUser.objects.all():
        user.dataset_migration_applied = False
        user.v2_speciality = None
        user.save()
    SkillToObject.objects.filter(content_type=ContentType.objects.get_for_model(CustomUser)).delete()

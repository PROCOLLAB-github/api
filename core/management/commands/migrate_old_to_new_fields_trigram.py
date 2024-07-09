from time import time

from django.db import transaction
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.search import TrigramSimilarity

from core.models import Specialization, Skill, SkillToObject

CustomUser = get_user_model()

# From 0.1 to 1 аdjust similarity threshold.
SIMULARITY: int = 0.1


class Command(BaseCommand):
    """
    Uses only with Postgres (TrigramSimilarity).
    Needs extension:
        $CREATE EXTENSION pg_trgm;
    Migrate old fields to new.
    """
    def handle(self, *args, **kwargs):
        self.stdout.write("Starting manual migrations...")
        try:
            start = time()
            migrate_old_to_new_fields_trigram()
            end = time()
            self.stdout.write(self.style.SUCCESS(
                f"Manual trigram migrations completed successfully, timing: {end - start}")
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Manual trigram migrations failed: {str(e)}"))


@transaction.atomic
def migrate_old_to_new_fields_trigram() -> None:
    """
    Custom trigram migration `speciality` -> `v2_speciality` and `key_skills` -> `skills`.
    Uses `TrigramSimilarity` and `SIMULARITY` for check similarity.
    """
    for user in CustomUser.objects.all():

        # Migration `speciality` -> `v2_speciality`.
        # (Only users who have not filled `v2_speciality`, but have filled in `speciality`).
        if user.speciality and not user.v2_speciality:
            searched_speciality = []
            for speciality_name in user.speciality.split(","):
                best_match: Specialization = (  # Searching best match.
                    Specialization.objects.annotate(
                        similarity=TrigramSimilarity("name", speciality_name),
                    )
                    .filter(similarity__gt=SIMULARITY)
                    .order_by("-similarity")
                    .first()
                )
                if best_match:
                    searched_speciality.append(best_match)
            # Choose best match.
            if searched_speciality:
                searched_speciality.sort(key=lambda x: x.similarity, reverse=True)
                user.v2_speciality = searched_speciality[0]

        # Migration `key_skills` -> `skills`.
        # (Only users who have not filled `skills`, but have filled in `key_skills`).
        if user.key_skills and not SkillToObject.objects.filter(object_id=user.id).exists():
            for skill_name in user.key_skills.lower().split(","):
                if not skill_name:
                    continue  # Skipping empty lines
                best_match: Skill = (  # Searching best match.
                    Skill.objects.annotate(
                        similarity=TrigramSimilarity("name", skill_name),
                    )
                    .filter(similarity__gt=SIMULARITY)
                    .order_by("-similarity")
                    .first()
                )
                if best_match:
                    SkillToObject.objects.get_or_create(
                        skill=best_match,
                        content_type=ContentType.objects.get_for_model(CustomUser),
                        object_id=user.id,
                    )

        # Boolean field is responsible for transferring data if both fields
        # were already there or were transferred = `True` (default value = `False`).
        if user.v2_speciality and SkillToObject.objects.filter(object_id=user.id).exists():
            user.dataset_migration_applied = True

        user.save()

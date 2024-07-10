from django.contrib.contenttypes.models import ContentType
from rest_framework import status

from core.models import Skill, SkillToObject
from rest_framework.response import Response

from vacancy.models import Vacancy


def update_vacancy_skills(request, vacancy: Vacancy):
    if "required_skills_ids" in request.data and request.data.get("required_skills_ids"):
        vacancy.required_skills.all().delete()

        needed_skills: list[int] = Skill.objects.filter(
            id__in=request.data["required_skills_ids"]
        ).values_list("id", flat=True)
        if non_existing_skills := set(request.data["required_skills_ids"]) - set(
            needed_skills
        ):
            return Response(
                f"Skills with ids: {non_existing_skills} does not exist",
                status=status.HTTP_400_BAD_REQUEST,
            )

        vacancy_content_type = ContentType.objects.get_for_model(Vacancy)
        to_create = [
            SkillToObject(
                skill_id=skill,
                content_type=vacancy_content_type,
                object_id=vacancy.id,
            )
            for skill in needed_skills
        ]
        SkillToObject.objects.bulk_create(to_create)

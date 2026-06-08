from types import SimpleNamespace

from django.test import TestCase

from vacancy.services import update_vacancy_skills
from vacancy.tests.helpers import create_skill, create_vacancy


class VacancyModelTests(TestCase):
    def test_datetime_closed_is_set_when_vacancy_becomes_inactive(self):
        vacancy = create_vacancy(is_active=True)

        vacancy.is_active = False
        vacancy.save()

        self.assertIsNotNone(vacancy.datetime_closed)

    def test_datetime_closed_is_cleared_when_vacancy_becomes_active(self):
        vacancy = create_vacancy(is_active=False)
        self.assertIsNotNone(vacancy.datetime_closed)

        vacancy.is_active = True
        vacancy.save()

        self.assertIsNone(vacancy.datetime_closed)


class VacancySkillsServiceTests(TestCase):
    def test_update_vacancy_skills_replaces_existing_skills(self):
        old_skill = create_skill(name="Old")
        new_skill = create_skill(name="New")
        vacancy = create_vacancy()
        vacancy.required_skills.create(skill=old_skill)
        request = SimpleNamespace(data={"required_skills_ids": [new_skill.id]})

        update_vacancy_skills(request, vacancy)

        self.assertEqual(
            list(vacancy.required_skills.values_list("skill_id", flat=True)),
            [new_skill.id],
        )

    def test_update_vacancy_skills_returns_error_for_missing_skill(self):
        vacancy = create_vacancy()
        request = SimpleNamespace(data={"required_skills_ids": [999999]})

        response = update_vacancy_skills(request, vacancy)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(vacancy.required_skills.exists())

    def test_get_required_skills_returns_skill_objects(self):
        skill = create_skill(name="Python")
        vacancy = create_vacancy()
        vacancy.required_skills.create(skill=skill)

        self.assertEqual(vacancy.get_required_skills(), [skill])

    def test_vacancy_string_representation_contains_role(self):
        vacancy = create_vacancy(role="Backend")

        self.assertEqual(str(vacancy), f"Vacancy<{vacancy.id}> - Backend")

    def test_vacancy_response_string_representation_contains_vacancy(self):
        vacancy = create_vacancy(role="Backend")
        response = vacancy.vacancy_requests.create(user=vacancy.project.leader)

        self.assertEqual(
            str(response),
            f"VacancyResponse<{response.id}> - {response.user} - {vacancy}",
        )

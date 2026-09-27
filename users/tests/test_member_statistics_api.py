from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from projects.models import Collaborator, Project
from users.models import CustomUser

from .helpers import add_user_to_program, build_partner_program, build_user


class MemberStatisticsAPITests(TestCase):
    """Счётчики проверяются через публичный HTTP-контракт, включая число SQL."""

    url = "/auth/public-users/stats/"

    def setUp(self):
        self.client = APIClient()

    def statistics(self, params=None):
        response = self.client.get(self.url, params or {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {"total", "in_projects", "in_programs", "new_last_30_days"},
        )
        self.assertTrue(all(type(value) is int for value in response.data.values()))
        return response.data

    def project(self, leader, **overrides):
        project = Project.objects.create(
            leader=leader, name="Синтетический проект", **{"draft": False, **overrides}
        )
        # Сигнал создаёт Collaborator лидера. Убираем его только в fixture,
        # чтобы независимо проверить оба источника участия и их пересечение.
        Collaborator.objects.filter(project=project, user=leader).delete()
        return project

    def test_empty_catalog_is_zero_and_public(self):
        self.assertEqual(
            self.statistics(),
            {"total": 0, "in_projects": 0, "in_programs": 0, "new_last_30_days": 0},
        )

    def test_only_active_members_enter_all_metrics(self):
        program = build_partner_program()
        for index, (kind, active) in enumerate(
            (
                (CustomUser.MEMBER, True),
                (CustomUser.MEMBER, False),
                (CustomUser.MENTOR, True),
                (CustomUser.EXPERT, True),
                (CustomUser.ADMIN, True),
                (CustomUser.INVESTOR, True),
            )
        ):
            user = build_user(
                email=f"role-{index}@example.test", user_type=kind, is_active=active
            )
            self.project(user)
            add_user_to_program(user, program)
        self.assertEqual(
            self.statistics(),
            {"total": 1, "in_projects": 1, "in_programs": 1, "new_last_30_days": 1},
        )

    def test_leader_counts_as_participant(self):
        self.project(build_user())
        self.assertEqual(self.statistics()["in_projects"], 1)

    def test_collaborator_counts_without_leadership(self):
        leader = build_user(email="mentor@example.test", user_type=CustomUser.MENTOR)
        Collaborator.objects.create(user=build_user(), project=self.project(leader))
        self.assertEqual(self.statistics()["in_projects"], 1)

    def test_multiple_projects_and_both_roles_count_a_person_once(self):
        leader = build_user()
        participant = build_user(email="participant@example.test")
        for _ in range(3):
            project = self.project(leader)
            Collaborator.objects.create(user=leader, project=project)
            Collaborator.objects.create(user=participant, project=project)
        self.assertEqual(self.statistics()["in_projects"], 2)

    def test_draft_and_private_projects_do_not_count_either_role(self):
        leader = build_user()
        participant = build_user(email="participant@example.test")
        for overrides in ({"draft": True}, {"is_public": False}):
            with self.subTest(overrides=overrides):
                Collaborator.objects.create(
                    user=participant, project=self.project(leader, **overrides)
                )
                self.assertEqual(self.statistics()["in_projects"], 0)

    def test_program_registrations_count_people_not_rows(self):
        user = build_user()
        for index in range(5):
            add_user_to_program(user, build_partner_program(tag=f"program-{index}"))
        self.assertEqual(self.statistics()["in_programs"], 1)

    def test_draft_program_does_not_count(self):
        add_user_to_program(build_user(), build_partner_program(draft=True))
        self.assertEqual(self.statistics()["in_programs"], 0)

    def test_thirty_day_boundary_is_inclusive_and_timezone_aware(self):
        now = timezone.now()
        for index, age in enumerate(
            (timedelta(days=1), timedelta(days=30), timedelta(days=30, microseconds=1))
        ):
            user = build_user(email=f"age-{index}@example.test")
            CustomUser.objects.filter(pk=user.pk).update(datetime_created=now - age)
        with patch("users.services.member_statistics.timezone.now", return_value=now):
            self.assertEqual(self.statistics()["new_last_30_days"], 2)

    def test_search_filters_and_pagination_do_not_change_statistics(self):
        build_user()
        expected = self.statistics()
        self.assertEqual(
            self.statistics(
                {
                    "fullname": "Несуществующий",
                    "skills__contains": "Несуществующий",
                    "speciality__icontains": "Несуществующий",
                    "offset": 999,
                    "limit": 0,
                    "user_type": CustomUser.EXPERT,
                }
            ),
            expected,
        )

    def test_response_is_only_numbers_without_personal_or_relation_data(self):
        user = build_user(email="private@example.test", first_name="Секрет")
        self.project(user)
        add_user_to_program(user, build_partner_program())
        response = self.client.get(self.url)
        self.assertEqual(len(response.data), 4)
        self.assertTrue(all(type(value) is int for value in response.data.values()))
        for forbidden in ("email", "id", "first_name", "project", "partner_program"):
            self.assertNotIn(forbidden, response.data)

    def test_non_read_methods_are_not_supported(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    def test_one_select_for_ten_hundred_and_thousand_users(self):
        """Подготовка данных вне замера: endpoint всегда делает один SELECT."""
        previous = 0
        for total in (10, 100, 1000):
            CustomUser.objects.bulk_create(
                [
                    CustomUser(
                        email=f"scale-{index}@example.test",
                        first_name="Участник",
                        last_name="Тестовый",
                        birthday=date(2000, 1, 1),
                        is_active=True,
                        user_type=CustomUser.MEMBER,
                    )
                    for index in range(previous, total)
                ]
            )
            previous = total
            with self.subTest(total=total), self.assertNumQueries(1):
                self.assertEqual(self.statistics()["total"], total)

    def test_query_count_stays_one_with_many_relations(self):
        user = build_user()
        for index in range(10):
            Collaborator.objects.create(user=user, project=self.project(user))
            add_user_to_program(user, build_partner_program(tag=f"related-{index}"))
        with self.assertNumQueries(1):
            self.assertEqual(self.statistics()["in_projects"], 1)

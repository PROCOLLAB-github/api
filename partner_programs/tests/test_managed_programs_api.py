# Roadmap: DEV-091

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.tests.helpers import create_partner_program, create_user


class ManagedProgramListAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="managed-program-manager")
        self.other_manager = create_user(prefix="managed-program-other-manager")
        self.participant = create_user(prefix="managed-program-participant")
        self.staff = create_user(prefix="managed-program-staff", is_staff=True)
        self.superuser = create_user(
            prefix="managed-program-superuser",
            is_staff=True,
            is_superuser=True,
        )
        self.published_program = create_partner_program(
            name="Янтарная программа",
            draft=False,
        )
        self.draft_program = create_partner_program(
            name="Альфа программа",
            draft=True,
        )
        self.other_program = create_partner_program(
            name="Бета программа",
            draft=False,
        )
        self.published_program.managers.add(self.manager)
        self.draft_program.managers.add(self.manager)
        self.other_program.managers.add(self.other_manager)
        self.url = reverse("partner_programs:managed-program-list")

    def get_as(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(self.url)

    def test_manager_sees_only_own_programs_including_drafts(self):
        response = self.get_as(self.manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            [
                {
                    "id": self.draft_program.pk,
                    "name": "Альфа программа",
                    "draft": True,
                },
                {
                    "id": self.published_program.pk,
                    "name": "Янтарная программа",
                    "draft": False,
                },
            ],
        )

    def test_programs_of_another_manager_are_not_disclosed(self):
        response = self.get_as(self.manager)

        returned_ids = {program["id"] for program in response.data}
        self.assertNotIn(self.other_program.pk, returned_ids)

    def test_participant_without_managed_programs_gets_empty_list(self):
        response = self.get_as(self.participant)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_staff_and_superuser_see_all_programs(self):
        expected_ids = [
            self.draft_program.pk,
            self.other_program.pk,
            self.published_program.pk,
        ]
        for user in (self.staff, self.superuser):
            with self.subTest(user=user.email):
                response = self.get_as(user)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [program["id"] for program in response.data],
                    expected_ids,
                )

    def test_anonymous_user_gets_401(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_order_is_stable_for_programs_with_same_name(self):
        first = create_partner_program(name="Одинаковое имя")
        second = create_partner_program(name="Одинаковое имя")
        first.managers.add(self.manager)
        second.managers.add(self.manager)

        response = self.get_as(self.manager)

        same_name_ids = [
            program["id"]
            for program in response.data
            if program["name"] == "Одинаковое имя"
        ]
        self.assertEqual(same_name_ids, [first.pk, second.pk])

    def test_program_count_does_not_increase_query_count(self):
        for index in range(10):
            program = create_partner_program(
                name="Масштаб {}".format(str(index).zfill(2))
            )
            program.managers.add(self.manager)
        self.client.force_authenticate(user=self.manager)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(queries), 1)

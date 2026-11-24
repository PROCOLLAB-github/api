from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from partner_programs.models import OrganizerGuideSeen
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from project_rates.tests.helpers import create_rate_expert


def help_state_url(program):
    return f"/programs/{program.pk}/management/help-state/"


class ManagementHelpStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organizer = create_user()
        cls.program = create_partner_program()
        cls.program.managers.add(cls.organizer)
        cls.url = help_state_url(cls.program)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.organizer)

    def test_persists_across_programs_and_sessions_per_user(self):
        another_program = create_partner_program(draft=True)
        another_program.managers.add(self.organizer)
        another_url = help_state_url(another_program)
        another_session = APIClient()
        another_session.force_authenticate(self.organizer)

        initial = self.client.get(self.url)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.data, {"seen": []})
        self.assertEqual(initial["Cache-Control"], "private, no-store")
        marked = self.client.post(
            self.url, {"guide": "participant-removal-v1"}, format="json"
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.data, {"seen": ["participant-removal-v1"]})
        self.assertEqual(marked["Cache-Control"], "private, no-store")
        across_programs = another_session.get(another_url)
        self.assertEqual(across_programs.status_code, 200)
        self.assertEqual(across_programs.data, marked.data)

        second_mark = another_session.post(
            another_url, {"guide": "certificates-v1"}, format="json"
        )
        self.assertEqual(second_mark.status_code, 200)
        self.assertEqual(
            self.client.get(self.url).data,
            {"seen": ["certificates-v1", "participant-removal-v1"]},
        )

        other_organizer = create_user()
        self.program.managers.add(other_organizer)
        another_session.force_authenticate(other_organizer)
        self.assertEqual(another_session.get(self.url).data, {"seen": []})

    def test_post_is_idempotent(self):
        for _ in range(2):
            response = self.client.post(
                self.url, {"guide": "allocation-shortage-v1"}, format="json"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, {"seen": ["allocation-shortage-v1"]})
        self.assertEqual(OrganizerGuideSeen.objects.count(), 1)

    def test_access_requires_management_of_requested_program_or_staff(self):
        unrelated_program = create_partner_program()
        self.assertEqual(
            self.client.get(help_state_url(unrelated_program)).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                help_state_url(unrelated_program),
                {"guide": "participant-empty-v1"},
                format="json",
            ).status_code,
            403,
        )
        participant = create_program_member(self.program).user
        expert = create_rate_expert(program=self.program)
        for user, code in [(None, 401), (participant, 403), (expert, 403)]:
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, code)
                self.assertEqual(
                    self.client.post(
                        self.url, {"guide": "participant-empty-v1"}, format="json"
                    ).status_code,
                    code,
                )
        self.assertFalse(OrganizerGuideSeen.objects.exists())

        staff = create_user(is_staff=True)
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.get(self.url).data, {"seen": []})
        marked = self.client.post(
            self.url, {"guide": "participant-empty-v1"}, format="json"
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.data, {"seen": ["participant-empty-v1"]})
        self.assertTrue(OrganizerGuideSeen.objects.filter(user=staff).exists())

    def test_draft_of_another_organizer_is_hidden(self):
        url = help_state_url(create_partner_program(draft=True))
        for response in (
            self.client.get(url),
            self.client.post(url, {"guide": "certificates-v1"}, format="json"),
        ):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data, {"detail": "Программа не найдена."})
        self.assertFalse(OrganizerGuideSeen.objects.exists())

    def test_rejects_invalid_guide_ids(self):
        for payload in (
            {},
            {"guide": None},
            {"guide": 1},
            {"guide": []},
            {"guide": ""},
            {"guide": "certificates-v2"},
            {"guide": " certificates-v1 "},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(self.url, payload, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("guide", response.data)
        self.assertFalse(OrganizerGuideSeen.objects.exists())


class ManagementHelpStateConcurrencyTests(TransactionTestCase):
    def test_concurrent_posts_for_same_guide_create_one_mark(self):
        if connection.vendor != "postgresql":
            self.skipTest("Тест конкурентной записи использует PostgreSQL.")
        organizer = create_user()
        program = create_partner_program()
        program.managers.add(organizer)
        url = help_state_url(program)
        barrier = Barrier(2, timeout=10)

        def mark_seen():
            try:
                client = APIClient()
                client.force_authenticate(organizer)
                barrier.wait()
                response = client.post(url, {"guide": "certificates-v1"}, format="json")
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(mark_seen)
            second = executor.submit(mark_seen)
            expected = (200, {"seen": ["certificates-v1"]})
            self.assertEqual(first.result(timeout=15), expected)
            self.assertEqual(second.result(timeout=15), expected)
        self.assertEqual(OrganizerGuideSeen.objects.count(), 1)

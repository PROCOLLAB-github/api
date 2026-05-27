from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_project,
    create_project,
    create_user,
)


class PartnerProgramProjectSubmitViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(prefix="submit-program-leader")

    def create_program(self, **overrides):
        defaults = {
            "is_competitive": True,
            "datetime_project_submission_ends": timezone.now()
            + timezone.timedelta(days=1),
        }
        defaults.update(overrides)
        return create_partner_program(**defaults)

    def create_project_link(self, program):
        project = create_project(leader=self.user, draft=False, is_public=False)
        return create_program_project(program, project=project)

    def test_submit_blocked_after_deadline(self):
        program = self.create_program(
            datetime_project_submission_ends=timezone.now() - timezone.timedelta(days=1)
        )
        link = self.create_project_link(program)
        self.client.force_authenticate(self.user)

        response = self.client.post(f"/programs/partner-program-projects/{link.pk}/submit/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data.get("detail"),
            "Срок подачи проектов в программу завершён.",
        )
        link.refresh_from_db()
        self.assertFalse(link.submitted)

    def test_submit_allowed_before_deadline(self):
        program = self.create_program()
        link = self.create_project_link(program)
        self.client.force_authenticate(self.user)

        response = self.client.post(f"/programs/partner-program-projects/{link.pk}/submit/")

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertTrue(link.submitted)
        self.assertIsNotNone(link.datetime_submitted)

    def test_submit_rejects_non_competitive_program(self):
        program = self.create_program(is_competitive=False)
        link = self.create_project_link(program)
        self.client.force_authenticate(self.user)

        response = self.client.post(f"/programs/partner-program-projects/{link.pk}/submit/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Программа не является конкурсной.")

    def test_submit_rejects_non_leader(self):
        program = self.create_program()
        link = self.create_project_link(program)
        outsider = create_user(prefix="submit-program-outsider")
        self.client.force_authenticate(outsider)

        response = self.client.post(f"/programs/partner-program-projects/{link.pk}/submit/")

        self.assertEqual(response.status_code, 403)

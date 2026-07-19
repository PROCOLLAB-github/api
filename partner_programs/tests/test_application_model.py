from django.core.exceptions import ValidationError
from django.test import TestCase

from partner_programs.models import Application
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
)


class ApplicationModelTests(TestCase):
    def test_can_create_draft_application_for_user_and_program(self):
        user = create_user(prefix="application-user")
        program = create_partner_program()

        application = Application.objects.create(
            program=program,
            user=user,
            created_by=user,
        )

        self.assertEqual(application.status, Application.STATUS_DRAFT)
        self.assertEqual(application.program, program)
        self.assertEqual(application.user, user)
        self.assertEqual(application.created_by, user)

    def test_cannot_create_second_active_application_for_same_user_and_program(self):
        user = create_user(prefix="application-active")
        program = create_partner_program()
        Application.objects.create(
            program=program,
            user=user,
            created_by=user,
            status=Application.STATUS_DRAFT,
        )

        with self.assertRaises(ValidationError) as error:
            Application.objects.create(
                program=program,
                user=user,
                created_by=user,
                status=Application.STATUS_SUBMITTED,
            )

        self.assertIn("user", error.exception.message_dict)

    def test_can_create_new_application_after_inactive_status(self):
        for inactive_status in (
            Application.STATUS_WITHDRAWN,
            Application.STATUS_REJECTED,
            Application.STATUS_CANCELLED,
        ):
            user = create_user(prefix=f"application-{inactive_status}")
            program = create_partner_program()
            Application.objects.create(
                program=program,
                user=user,
                created_by=user,
                status=inactive_status,
            )

            application = Application.objects.create(
                program=program,
                user=user,
                created_by=user,
                status=Application.STATUS_DRAFT,
            )

            self.assertEqual(application.status, Application.STATUS_DRAFT)

    def test_created_by_is_required(self):
        user = create_user(prefix="application-created-by")
        program = create_partner_program()
        application = Application(
            program=program,
            user=user,
        )

        with self.assertRaises(ValidationError) as error:
            application.full_clean()

        self.assertIn("created_by", error.exception.message_dict)

    def test_form_data_defaults_to_dict(self):
        user = create_user(prefix="application-form-data")
        program = create_partner_program()

        application = Application.objects.create(
            program=program,
            user=user,
            created_by=user,
        )

        self.assertEqual(application.form_data, {})
        self.assertIsInstance(application.form_data, dict)

    def test_project_and_status_timestamps_can_be_null(self):
        user = create_user(prefix="application-nullable")
        program = create_partner_program()

        application = Application.objects.create(
            program=program,
            user=user,
            created_by=user,
        )

        self.assertIsNone(application.project)
        self.assertIsNone(application.submitted_at)
        self.assertIsNone(application.approved_at)
        self.assertIsNone(application.rejected_at)
        self.assertIsNone(application.withdrawn_at)

    def test_project_can_be_attached(self):
        user = create_user(prefix="application-project")
        program = create_partner_program()
        project = create_project(leader=user)

        application = Application.objects.create(
            program=program,
            user=user,
            created_by=user,
            project=project,
        )

        self.assertEqual(application.project, project)

    def test_status_choices_accept_expected_values(self):
        for status, _label in Application.STATUS_CHOICES:
            user = create_user(prefix=f"application-{status}")
            program = create_partner_program()

            application = Application.objects.create(
                program=program,
                user=user,
                created_by=user,
                status=status,
            )

            self.assertEqual(application.status, status)

    def test_status_choices_reject_unknown_value(self):
        user = create_user(prefix="application-invalid-status")
        program = create_partner_program()
        application = Application(
            program=program,
            user=user,
            created_by=user,
            status="unknown",
        )

        with self.assertRaises(ValidationError) as error:
            application.full_clean()

        self.assertIn("status", error.exception.message_dict)

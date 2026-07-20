from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.test import TestCase

from partner_programs.models import Application, Submission
from partner_programs.tests.helpers import create_partner_program, create_user


class SubmissionModelTests(TestCase):
    def setUp(self):
        self.user = create_user(prefix="submission-user")
        self.program = create_partner_program()
        self.application = Application.objects.create(
            program=self.program,
            user=self.user,
            created_by=self.user,
        )

    def create_submission(self, **overrides):
        values = {
            "application": self.application,
            "program": self.program,
            "submitted_by": self.user,
            "title": "MVP solution",
        }
        values.update(overrides)
        return Submission.objects.create(**values)

    def test_can_create_draft_submission_for_application(self):
        submission = self.create_submission()

        self.assertEqual(submission.application, self.application)
        self.assertEqual(submission.program, self.program)
        self.assertEqual(submission.submitted_by, self.user)
        self.assertEqual(submission.status, Submission.STATUS_DRAFT)

    def test_form_data_defaults_to_dict(self):
        submission = self.create_submission()

        self.assertEqual(submission.form_data, {})
        self.assertIsInstance(submission.form_data, dict)

    def test_links_default_to_list(self):
        submission = self.create_submission()

        self.assertEqual(submission.links, [])
        self.assertIsInstance(submission.links, list)

    def test_status_defaults_to_draft(self):
        submission = self.create_submission()

        self.assertEqual(submission.status, Submission.STATUS_DRAFT)

    def test_version_defaults_to_one(self):
        submission = self.create_submission()

        self.assertEqual(submission.version, 1)

    def test_stage_key_defaults_to_main(self):
        submission = self.create_submission()

        self.assertEqual(submission.stage_key, "main")

    def test_project_is_not_required_or_present_on_submission(self):
        submission = self.create_submission()

        with self.assertRaises(FieldDoesNotExist):
            Submission._meta.get_field("project")
        self.assertIsNotNone(submission.pk)

    def test_application_is_required(self):
        submission = Submission(
            program=self.program,
            submitted_by=self.user,
            title="Missing application",
        )

        with self.assertRaises(ValidationError) as error:
            submission.full_clean()

        self.assertIn("application", error.exception.message_dict)

    def test_program_is_required(self):
        submission = Submission(
            application=self.application,
            submitted_by=self.user,
            title="Missing program",
        )

        with self.assertRaises(ValidationError) as error:
            submission.full_clean()

        self.assertIn("program", error.exception.message_dict)

    def test_submitted_by_is_required(self):
        submission = Submission(
            application=self.application,
            program=self.program,
            title="Missing submitter",
        )

        with self.assertRaises(ValidationError) as error:
            submission.full_clean()

        self.assertIn("submitted_by", error.exception.message_dict)

    def test_program_must_match_application_program(self):
        other_program = create_partner_program()

        with self.assertRaises(ValidationError) as error:
            self.create_submission(program=other_program)

        self.assertIn("program", error.exception.message_dict)

    def test_submitted_by_must_match_application_owner_or_creator(self):
        other_user = create_user(prefix="submission-other-user")

        with self.assertRaises(ValidationError) as error:
            self.create_submission(submitted_by=other_user)

        self.assertIn("submitted_by", error.exception.message_dict)

    def test_inactive_application_cannot_have_submission(self):
        for status in (
            Application.STATUS_WITHDRAWN,
            Application.STATUS_REJECTED,
            Application.STATUS_CANCELLED,
        ):
            with self.subTest(status=status):
                self.application.status = status
                self.application.save()

                with self.assertRaises(ValidationError) as error:
                    self.create_submission()

                self.assertIn("application", error.exception.message_dict)

    def test_duplicate_application_stage_and_version_is_rejected(self):
        self.create_submission()

        with self.assertRaises(ValidationError):
            self.create_submission(title="Duplicate solution")

    def test_version_two_is_allowed_for_same_application_and_stage(self):
        self.create_submission()

        version_two = self.create_submission(title="Version two", version=2)

        self.assertEqual(version_two.version, 2)

    def test_other_stage_is_allowed_for_same_application_and_version(self):
        self.create_submission()

        other_stage = self.create_submission(title="Final stage", stage_key="final")

        self.assertEqual(other_stage.stage_key, "final")

    def test_version_must_be_at_least_one(self):
        with self.assertRaises(ValidationError):
            self.create_submission(version=0)

    def test_can_edit_for_draft_and_returned_only(self):
        for status in (Submission.STATUS_DRAFT, Submission.STATUS_RETURNED):
            with self.subTest(status=status):
                submission = Submission(status=status)
                self.assertTrue(submission.can_edit)

        for status in (
            Submission.STATUS_SUBMITTED,
            Submission.STATUS_FINAL,
            Submission.STATUS_CANCELLED,
        ):
            with self.subTest(status=status):
                submission = Submission(status=status)
                self.assertFalse(submission.can_edit)

    def test_can_submit_for_draft_and_returned_only(self):
        for status in (Submission.STATUS_DRAFT, Submission.STATUS_RETURNED):
            with self.subTest(status=status):
                submission = Submission(status=status)
                self.assertTrue(submission.can_submit)

        for status in (
            Submission.STATUS_SUBMITTED,
            Submission.STATUS_FINAL,
            Submission.STATUS_CANCELLED,
        ):
            with self.subTest(status=status):
                submission = Submission(status=status)
                self.assertFalse(submission.can_submit)

    def test_status_helpers(self):
        self.assertTrue(Submission(status=Submission.STATUS_DRAFT).is_draft)
        self.assertTrue(Submission(status=Submission.STATUS_SUBMITTED).is_submitted)
        self.assertTrue(Submission(status=Submission.STATUS_FINAL).is_final)

    def test_submitted_at_can_be_null(self):
        submission = self.create_submission()

        self.assertIsNone(submission.submitted_at)

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import Application, Submission
from partner_programs.tests.helpers import create_partner_program, create_user


def throttle_settings(**rates):
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        **rest_framework.get("DEFAULT_THROTTLE_RATES", {}),
        **rates,
    }
    return rest_framework


class SubmissionAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = create_user(prefix="submission-api-owner")
        self.other_user = create_user(prefix="submission-api-other")
        self.staff_user = create_user(prefix="submission-api-staff", is_staff=True)
        self.program = create_partner_program()
        self.application = self.create_application()

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def create_application(
        self,
        *,
        user=None,
        status=Application.STATUS_SUBMITTED,
    ):
        owner = user or self.user
        return Application.objects.create(
            program=self.program,
            user=owner,
            created_by=owner,
            status=status,
            submitted_at=(
                timezone.now() if status == Application.STATUS_SUBMITTED else None
            ),
        )

    def create_submission(self, **overrides):
        values = {
            "application": self.application,
            "program": self.program,
            "submitted_by": self.user,
            "title": "Solution",
        }
        values.update(overrides)
        return Submission.objects.create(**values)

    @property
    def list_url(self):
        return f"/applications/{self.application.id}/submissions/"

    def test_unauthenticated_user_cannot_list_or_create_submissions(self):
        list_response = self.client.get(self.list_url)
        create_response = self.client.post(
            self.list_url,
            {"title": "Unauthorized solution"},
            format="json",
        )

        self.assertEqual(list_response.status_code, 401)
        self.assertEqual(create_response.status_code, 401)
        self.assertFalse(Submission.objects.exists())

    def test_owner_can_list_own_application_submissions_newest_first(self):
        first = self.create_submission(version=1)
        second = self.create_submission(title="Version two", version=2)
        self.authenticate()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [second.id, first.id])

    def test_listing_empty_application_does_not_create_submission(self):
        self.authenticate()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])
        self.assertFalse(Submission.objects.exists())

    def test_user_cannot_list_another_users_application_submissions(self):
        other_application = self.create_application(user=self.other_user)
        self.authenticate()

        response = self.client.get(
            f"/applications/{other_application.id}/submissions/"
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_can_create_draft_for_submitted_or_approved_application(self):
        self.authenticate()

        submitted_response = self.client.post(
            self.list_url,
            {"title": "Submitted application solution"},
            format="json",
        )
        self.application.status = Application.STATUS_APPROVED
        self.application.save()
        approved_response = self.client.post(
            self.list_url,
            {"title": "Approved application solution"},
            format="json",
        )

        self.assertEqual(submitted_response.status_code, 201)
        self.assertEqual(approved_response.status_code, 201)
        self.assertEqual(submitted_response.data["status"], Submission.STATUS_DRAFT)
        self.assertEqual(approved_response.data["status"], Submission.STATUS_DRAFT)

    def test_cannot_create_for_ineligible_application_status(self):
        self.authenticate()

        for application_status in (
            Application.STATUS_DRAFT,
            Application.STATUS_WITHDRAWN,
            Application.STATUS_REJECTED,
            Application.STATUS_CANCELLED,
        ):
            with self.subTest(status=application_status):
                self.application.status = application_status
                self.application.save()

                response = self.client.post(
                    self.list_url,
                    {"title": "Invalid application solution"},
                    format="json",
                )

                self.assertEqual(response.status_code, 400)

        self.assertFalse(Submission.objects.exists())

    def test_create_fills_program_and_submitted_by(self):
        self.authenticate()

        response = self.client.post(
            self.list_url,
            {"title": "Owned solution"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        submission = Submission.objects.get()
        self.assertEqual(submission.program, self.application.program)
        self.assertEqual(submission.submitted_by, self.user)
        self.assertEqual(response.data["program"], self.program.id)
        self.assertEqual(response.data["submitted_by"], self.user.id)

    def test_staff_can_create_submission(self):
        self.authenticate(self.staff_user)

        response = self.client.post(
            self.list_url,
            {"title": "Staff-created solution"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Submission.objects.get().submitted_by, self.staff_user)

    def test_default_stage_key_is_main(self):
        self.authenticate()

        response = self.client.post(
            self.list_url,
            {"title": "Main stage solution"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["stage_key"], "main")

    def test_default_version_uses_next_stage_version(self):
        self.create_submission(stage_key="main", version=1)
        self.create_submission(title="Other stage", stage_key="final", version=7)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            {"title": "Next main version", "stage_key": "main"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["version"], 2)

    def test_duplicate_stage_and_version_returns_validation_error(self):
        self.create_submission(stage_key="main", version=1)
        self.authenticate()

        response = self.client.post(
            self.list_url,
            {"title": "Duplicate", "stage_key": "main", "version": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("version", response.data)
        self.assertEqual(Submission.objects.count(), 1)

    def test_owner_can_get_submission_detail(self):
        submission = self.create_submission()
        self.authenticate()

        response = self.client.get(f"/submissions/{submission.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], submission.id)

    def test_user_cannot_get_another_users_submission(self):
        other_application = self.create_application(user=self.other_user)
        submission = self.create_submission(
            application=other_application,
            submitted_by=self.other_user,
        )
        self.authenticate()

        response = self.client.get(f"/submissions/{submission.id}/")

        self.assertEqual(response.status_code, 404)

    def test_patch_draft_updates_editable_fields(self):
        submission = self.create_submission()
        self.authenticate()

        response = self.client.patch(
            f"/submissions/{submission.id}/",
            {
                "title": "Updated solution",
                "description": "Updated description",
                "form_data": {"answer": 42},
                "links": ["https://example.com/solution"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.title, "Updated solution")
        self.assertEqual(submission.description, "Updated description")
        self.assertEqual(submission.form_data, {"answer": 42})
        self.assertEqual(submission.links, ["https://example.com/solution"])

    def test_patch_non_editable_status_is_rejected(self):
        submission = self.create_submission()
        self.authenticate()

        for submission_status in (
            Submission.STATUS_SUBMITTED,
            Submission.STATUS_FINAL,
            Submission.STATUS_CANCELLED,
        ):
            with self.subTest(status=submission_status):
                submission.status = submission_status
                submission.save()

                response = self.client.patch(
                    f"/submissions/{submission.id}/",
                    {"title": "Should not change"},
                    format="json",
                )

                self.assertEqual(response.status_code, 400)

        submission.refresh_from_db()
        self.assertEqual(submission.title, "Solution")

    def test_patch_rejects_immutable_fields(self):
        submission = self.create_submission()
        other_application = self.create_application(user=self.other_user)
        other_program = create_partner_program()
        self.authenticate()

        response = self.client.patch(
            f"/submissions/{submission.id}/",
            {
                "application": other_application.id,
                "program": other_program.id,
                "submitted_by": self.other_user.id,
                "status": Submission.STATUS_FINAL,
                "stage_key": "other",
                "version": 9,
                "submitted_at": timezone.now().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        submission.refresh_from_db()
        self.assertEqual(submission.application, self.application)
        self.assertEqual(submission.program, self.program)
        self.assertEqual(submission.submitted_by, self.user)
        self.assertEqual(submission.status, Submission.STATUS_DRAFT)
        self.assertEqual(submission.stage_key, "main")
        self.assertEqual(submission.version, 1)
        self.assertIsNone(submission.submitted_at)

    def test_submit_draft_sets_status_and_submitted_at(self):
        submission = self.create_submission()
        self.authenticate()

        response = self.client.post(
            f"/submissions/{submission.id}/submit/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_SUBMITTED)
        self.assertIsNotNone(submission.submitted_at)

    def test_repeated_submit_preserves_submitted_at(self):
        submission = self.create_submission()
        self.authenticate()
        url = f"/submissions/{submission.id}/submit/"

        first_response = self.client.post(url, {}, format="json")
        submission.refresh_from_db()
        first_submitted_at = submission.submitted_at
        second_response = self.client.post(url, {}, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.submitted_at, first_submitted_at)

    def test_submit_final_or_cancelled_returns_bad_request(self):
        submission = self.create_submission()
        self.authenticate()

        for submission_status in (
            Submission.STATUS_FINAL,
            Submission.STATUS_CANCELLED,
        ):
            with self.subTest(status=submission_status):
                submission.status = submission_status
                submission.save()

                response = self.client.post(
                    f"/submissions/{submission.id}/submit/",
                    {},
                    format="json",
                )

                self.assertEqual(response.status_code, 400)

    def test_cancel_draft_is_idempotent(self):
        submission = self.create_submission()
        self.authenticate()
        url = f"/submissions/{submission.id}/cancel/"

        first_response = self.client.post(url, {}, format="json")
        second_response = self.client.post(url, {}, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.STATUS_CANCELLED)

    def test_cancel_submitted_or_final_returns_bad_request(self):
        submission = self.create_submission()
        self.authenticate()

        for submission_status in (
            Submission.STATUS_SUBMITTED,
            Submission.STATUS_FINAL,
        ):
            with self.subTest(status=submission_status):
                submission.status = submission_status
                submission.save()

                response = self.client.post(
                    f"/submissions/{submission.id}/cancel/",
                    {},
                    format="json",
                )

                self.assertEqual(response.status_code, 400)

    @override_settings(REST_FRAMEWORK=throttle_settings(submission_create="1/min"))
    def test_submission_create_is_scoped_throttled(self):
        self.authenticate()

        first_response = self.client.post(
            self.list_url,
            {"title": "First solution"},
            format="json",
            REMOTE_ADDR="203.0.113.50",
        )
        second_response = self.client.post(
            self.list_url,
            {"title": "Second solution"},
            format="json",
            REMOTE_ADDR="203.0.113.50",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 429)

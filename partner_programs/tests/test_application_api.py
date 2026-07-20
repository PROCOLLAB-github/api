from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    Application,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
)
from projects.models import Project


def throttle_settings(**rates):
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        **rest_framework.get("DEFAULT_THROTTLE_RATES", {}),
        **rates,
    }
    return rest_framework


class ApplicationAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = create_user(prefix="application-api-owner")
        self.other_user = create_user(prefix="application-api-other")
        self.staff_user = create_user(prefix="application-api-staff", is_staff=True)
        self.program = create_partner_program()

    def authenticate(self, user=None):
        self.client.force_authenticate(user=user or self.user)

    def create_application(self, *, user=None, status=Application.STATUS_DRAFT, **data):
        owner = user or self.user
        return Application.objects.create(
            program=self.program,
            user=owner,
            created_by=owner,
            status=status,
            **data,
        )

    def test_unauthenticated_user_cannot_create_application(self):
        response = self.client.post(
            f"/programs/{self.program.id}/applications/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Application.objects.exists())

    def test_authenticated_user_can_create_draft_application(self):
        self.authenticate()

        response = self.client.post(
            f"/programs/{self.program.id}/applications/",
            {"form_data": {"motivation": "Build a useful project"}},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        application = Application.objects.get()
        self.assertEqual(application.status, Application.STATUS_DRAFT)
        self.assertEqual(application.program, self.program)
        self.assertEqual(application.user, self.user)
        self.assertEqual(application.created_by, self.user)
        self.assertEqual(
            application.form_data,
            {"motivation": "Build a useful project"},
        )
        self.assertIsNone(application.project)
        self.assertEqual(response.data["id"], application.id)
        self.assertEqual(response.data["project"], None)
        self.assertFalse(PartnerProgramUserProfile.objects.exists())
        self.assertFalse(PartnerProgramProject.objects.exists())
        self.assertFalse(Project.objects.exists())

    def test_my_application_returns_current_users_application(self):
        application = self.create_application()
        self.authenticate()

        response = self.client.get(f"/programs/{self.program.id}/applications/my/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], application.id)
        self.assertEqual(response.data["user"], self.user.id)

    def test_my_application_does_not_return_another_users_application(self):
        self.create_application(user=self.other_user)
        self.authenticate()

        response = self.client.get(f"/programs/{self.program.id}/applications/my/")

        self.assertEqual(response.status_code, 404)

    def test_owner_can_read_application_detail(self):
        application = self.create_application()
        self.authenticate()

        response = self.client.get(f"/applications/{application.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], application.id)

    def test_repeated_create_returns_existing_active_application(self):
        self.authenticate()
        url = f"/programs/{self.program.id}/applications/"

        first_response = self.client.post(
            url,
            {"form_data": {"version": 1}},
            format="json",
        )
        second_response = self.client.post(
            url,
            {"form_data": {"version": 2}},
            format="json",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.data["id"], second_response.data["id"])
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(Application.objects.get().form_data, {"version": 1})

    def test_patch_draft_updates_form_data(self):
        application = self.create_application(form_data={"version": 1})
        self.authenticate()

        response = self.client.patch(
            f"/applications/{application.id}/",
            {"form_data": {"version": 2}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.form_data, {"version": 2})

    def test_patch_rejects_immutable_application_fields(self):
        application = self.create_application(form_data={"version": 1})
        other_program = create_partner_program()
        self.authenticate()

        response = self.client.patch(
            f"/applications/{application.id}/",
            {
                "program": other_program.id,
                "user": self.other_user.id,
                "created_by": self.other_user.id,
                "status": Application.STATUS_APPROVED,
                "form_data": {"version": 2},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        application.refresh_from_db()
        self.assertEqual(application.program, self.program)
        self.assertEqual(application.user, self.user)
        self.assertEqual(application.created_by, self.user)
        self.assertEqual(application.status, Application.STATUS_DRAFT)
        self.assertEqual(application.form_data, {"version": 1})

    def test_patch_submitted_application_is_rejected(self):
        application = self.create_application(
            status=Application.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.authenticate()

        response = self.client.patch(
            f"/applications/{application.id}/",
            {"form_data": {"changed": True}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        application.refresh_from_db()
        self.assertEqual(application.form_data, {})

    def test_submit_transitions_draft_and_sets_submitted_at(self):
        application = self.create_application()
        self.authenticate()

        response = self.client.post(
            f"/applications/{application.id}/submit/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.STATUS_SUBMITTED)
        self.assertIsNotNone(application.submitted_at)
        self.assertEqual(response.data["status"], Application.STATUS_SUBMITTED)

    def test_repeated_submit_preserves_submitted_at(self):
        application = self.create_application()
        self.authenticate()
        url = f"/applications/{application.id}/submit/"

        first_response = self.client.post(url, {}, format="json")
        application.refresh_from_db()
        first_submitted_at = application.submitted_at
        second_response = self.client.post(url, {}, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.submitted_at, first_submitted_at)

    def test_withdraw_transitions_application_and_is_idempotent(self):
        application = self.create_application(
            status=Application.STATUS_SUBMITTED,
            submitted_at=timezone.now(),
        )
        self.authenticate()
        url = f"/applications/{application.id}/withdraw/"

        first_response = self.client.post(url, {}, format="json")
        application.refresh_from_db()
        first_withdrawn_at = application.withdrawn_at
        second_response = self.client.post(url, {}, format="json")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.STATUS_WITHDRAWN)
        self.assertIsNotNone(application.withdrawn_at)
        self.assertEqual(application.withdrawn_at, first_withdrawn_at)

    def test_rejected_or_cancelled_application_cannot_be_withdrawn(self):
        self.authenticate()

        for application_status in (
            Application.STATUS_REJECTED,
            Application.STATUS_CANCELLED,
        ):
            application = self.create_application(status=application_status)

            response = self.client.post(
                f"/applications/{application.id}/withdraw/",
                {},
                format="json",
            )

            self.assertEqual(response.status_code, 400)
            application.refresh_from_db()
            self.assertEqual(application.status, application_status)

    def test_user_can_create_new_application_after_withdrawal(self):
        withdrawn_application = self.create_application(
            status=Application.STATUS_WITHDRAWN,
            withdrawn_at=timezone.now(),
        )
        self.authenticate()

        response = self.client.post(
            f"/programs/{self.program.id}/applications/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.data["id"], withdrawn_application.id)
        self.assertEqual(Application.objects.count(), 2)

    def test_user_cannot_read_or_change_another_users_application(self):
        application = self.create_application(user=self.other_user)
        self.authenticate()
        detail_url = f"/applications/{application.id}/"

        get_response = self.client.get(detail_url)
        patch_response = self.client.patch(
            detail_url,
            {"form_data": {"changed": True}},
            format="json",
        )
        submit_response = self.client.post(
            f"/applications/{application.id}/submit/",
            {},
            format="json",
        )
        withdraw_response = self.client.post(
            f"/applications/{application.id}/withdraw/",
            {},
            format="json",
        )

        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(patch_response.status_code, 404)
        self.assertEqual(submit_response.status_code, 404)
        self.assertEqual(withdraw_response.status_code, 404)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.STATUS_DRAFT)
        self.assertEqual(application.form_data, {})

    def test_staff_can_read_application(self):
        application = self.create_application()
        self.authenticate(self.staff_user)

        response = self.client.get(f"/applications/{application.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], application.id)

    def test_staff_can_submit_and_withdraw_application(self):
        application = self.create_application()
        self.authenticate(self.staff_user)

        submit_response = self.client.post(
            f"/applications/{application.id}/submit/",
            {},
            format="json",
        )
        withdraw_response = self.client.post(
            f"/applications/{application.id}/withdraw/",
            {},
            format="json",
        )

        self.assertEqual(submit_response.status_code, 200)
        self.assertEqual(withdraw_response.status_code, 200)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.STATUS_WITHDRAWN)

    def test_project_can_be_null(self):
        self.authenticate()

        response = self.client.post(
            f"/programs/{self.program.id}/applications/",
            {"project_id": None},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["project"], None)
        self.assertIsNone(Application.objects.get().project)

    def test_user_can_attach_project_they_lead(self):
        project = create_project(leader=self.user)
        self.authenticate()

        response = self.client.post(
            f"/programs/{self.program.id}/applications/",
            {"project_id": project.id},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["project"], project.id)
        self.assertEqual(Application.objects.get().project, project)

    def test_user_cannot_attach_another_users_project(self):
        project = create_project(leader=self.other_user)
        self.authenticate()

        response = self.client.post(
            f"/programs/{self.program.id}/applications/",
            {"project_id": project.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Application.objects.exists())

    @override_settings(REST_FRAMEWORK=throttle_settings(application_create="1/min"))
    def test_application_create_is_scoped_throttled(self):
        self.authenticate()
        url = f"/programs/{self.program.id}/applications/"

        first_response = self.client.post(
            url,
            {},
            format="json",
            REMOTE_ADDR="203.0.113.30",
        )
        second_response = self.client.post(
            url,
            {},
            format="json",
            REMOTE_ADDR="203.0.113.30",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 429)

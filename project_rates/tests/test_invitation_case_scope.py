from django.core import mail
from django.test import TestCase, override_settings

from partner_programs.models import PartnerProgramField
from project_rates.models import ExpertCaseScope, ExpertInvitation
from project_rates.tests.helpers import create_rate_user
from project_rates.tests import test_workspace as fixtures


@override_settings(
    EXPERT_WORKSPACE_FRONTEND_URL="https://dev.procollab.ru",
    EMAIL_USER="no-reply@example.com",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_BROKER_URL="memory://",
    CELERY_RESULT_BACKEND="cache+memory://",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class InvitationCaseScopeTests(TestCase):
    """The organizer's choice survives delivery, acceptance and later edits."""

    post = fixtures.WorkspaceTests.post
    invitation = fixtures.WorkspaceTests.invitation

    def setUp(self):
        fixtures.WorkspaceTests.setUp(self)
        self.field = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="case",
            label="Кейс",
            field_type="select",
            show_filter=True,
            options="Сбер|Т-Банк",
            is_required=True,
        )

    def new_invitation(self, **scope):
        with self.captureOnCommitCallbacks(execute=True):
            return self.post(
                self.root + "experts/",
                {
                    "email": "invitation-scope@example.com",
                    **scope,
                },
            )

    def test_invite_requires_explicit_nonempty_valid_scope(self):
        for data in (
            {},
            {"all_cases": False, "case_names": []},
            {"all_cases": False, "case_names": ["Чужой кейс"]},
        ):
            self.assertEqual(self.new_invitation(**data).status_code, 400)
        self.assertFalse(ExpertInvitation.objects.exists())
        self.assertFalse(getattr(mail, "outbox", []))

    def test_selected_cases_survive_resend_acceptance_and_idempotent_replay(self):
        result = self.new_invitation(
            all_cases=False, case_names=["Сбер", "Т-Банк", "Сбер"]
        )
        self.assertEqual(result.status_code, 201, result.data)
        invitation = ExpertInvitation.objects.get()
        self.assertFalse(invitation.all_cases)
        self.assertEqual(invitation.case_names, ["Сбер", "Т-Банк"])
        with self.captureOnCommitCallbacks(execute=True):
            resent = self.post(
                self.root + f"expert-invitations/{invitation.pk}/resend/", {}
            )
        self.assertEqual(resent.status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.case_names, ["Сбер", "Т-Банк"])
        user = create_rate_user()
        user.email = invitation.email
        user.save()
        self.client.force_authenticate(user)
        url = f"/evaluation/own-invitations/{invitation.pk}/accept/"
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.post(url, {}).status_code, 200)
        scope = ExpertCaseScope.objects.get(
            expert__user=user, partner_program=self.program
        )
        self.assertFalse(scope.all_cases)
        self.assertEqual(scope.case_names, ["Сбер", "Т-Банк"])
        scope.case_names = ["Т-Банк"]
        scope.save()
        self.assertEqual(self.post(url, {}).status_code, 200)
        scope.refresh_from_db()
        self.assertEqual(scope.case_names, ["Т-Банк"])

    def test_pending_scope_can_be_changed_and_old_revision_is_rejected(self):
        invitation, _ = self.invitation()
        state = self.client.get(self.root + "experts/").data
        url = self.root + f"expert-invitations/{invitation.pk}/cases/"
        data = {"revision": state["revision"], "all_cases": False, "case_names": ["Сбер"]}
        response = self.post(url, data)
        self.assertEqual(response.status_code, 200, response.data)
        row = next(
            r for r in response.data["experts"] if r.get("invitation_id") == invitation.pk
        )
        self.assertEqual(row["case_names"], ["Сбер"])
        self.assertFalse(row["all_cases"])
        self.assertEqual(self.post(url, data).status_code, 409)
        data.update(
            revision=response.data["revision"], all_cases=True, case_names=["Сбер"]
        )
        self.assertEqual(self.post(url, data).status_code, 200)
        invitation.refresh_from_db()
        self.assertEqual(invitation.case_names, [])

    def test_project_total_does_not_change_with_filters(self):
        response = self.client.get(self.root + "projects/", {"search": "no-such-project"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["total_count"], 1)

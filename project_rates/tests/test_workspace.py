import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.services.analytics import _solution_rows
from project_rates.models import ExpertInvitation, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_user,
    create_rate_expert,
    create_rate_project,
    create_rate_criteria,
    link_project_to_program,
)
from project_rates.workspace import digest, target
from users.models import CustomUser, Expert
from users.serializers import UserListSerializer


@override_settings(
    EXPERT_WORKSPACE_FRONTEND_URL="https://dev.procollab.ru",
    EMAIL_USER="no-reply@example.com",
)
class WorkspaceTests(TestCase):
    def test_regular_profile_cannot_clear_birthday(self):
        response = self.client.patch(
            f"/auth/users/{self.manager.pk}/", {"birthday": None}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.manager.refresh_from_db()
        self.assertIsNotNone(self.manager.birthday)

    @patch("project_rates.services.send_email.delay")
    def test_managed_scoring_respects_submission_own_team_and_deadline(self, send):
        self.enable(1)
        ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=self.project, expert=self.expert.expert
        )
        self.client.force_authenticate(self.expert)
        payload = [{"criterion_id": self.criterion.pk, "value": "0"}]
        url = f"/rate-project/rate/{self.project.pk}"
        type(self.link).objects.filter(pk=self.link.pk).update(submitted=False)
        self.assertEqual(self.post(url, payload).status_code, 400)
        type(self.link).objects.filter(pk=self.link.pk).update(submitted=True)
        type(self.project).objects.filter(pk=self.project.pk).update(leader=self.expert)
        self.assertEqual(self.post(url, payload).status_code, 400)
        type(self.project).objects.filter(pk=self.project.pk).update(
            leader_id=self.project.leader_id
        )
        self.program.datetime_evaluation_ends = timezone.now() - timedelta(seconds=1)
        self.program.save()
        self.assertEqual(self.post(url, payload).status_code, 400)
        self.assertFalse(ProjectScore.objects.exists())
        send.assert_not_called()

    def test_existing_mixed_case_email_keeps_working_in_invitation_login(self):
        self.manager.email = "MixedCase@example.com"
        self.manager.save()
        invitation, token = self.invitation("mixedcase@example.com")
        self.client.force_authenticate(None)
        preview = self.client.get(f"/evaluation/invitations/{token}/").data
        self.assertTrue(preview["account_exists"])
        self.assertEqual(preview["login_email"], self.manager.email)
        result = self.post(
            "/api/token/", {"email": preview["login_email"], "password": "pass"}
        )
        self.assertEqual(result.status_code, 200, result.data)

    def setUp(self):
        self.program = create_rate_program(is_competitive=True)
        self.manager = create_rate_user()
        self.program.managers.add(self.manager)
        self.expert = create_rate_expert(program=self.program)
        self.project = create_rate_project()
        self.program.users.add(
            self.project.leader, through_defaults={"partner_program_data": {}}
        )
        self.link = link_project_to_program(self.program, self.project)
        self.link.submitted = True
        self.link.save()
        self.criterion = create_rate_criteria(self.program)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.root = f"/programs/{self.program.pk}/management/"

    def post(self, path, data):
        return self.client.post(path, data, format="json")

    def enable(self, number=2):
        self.program.required_evaluators = number
        self.program.is_distributed_evaluation = True
        self.program.save()

    def invitation(
        self, email="new-expert@example.com", token="test-invitation-token-0123456789"
    ):
        return (
            ExpertInvitation.objects.create(
                partner_program=self.program,
                email=email,
                invited_by=self.manager,
                token_digest=digest(token),
                expires_at=timezone.now() + timedelta(days=7),
            ),
            token,
        )

    def test_manager_invite_delivery_digest_duplicate_and_role_scope(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                self.root + "experts/", {"email": "New-Expert@EXAMPLE.COM"}
            )
        self.assertEqual(response.status_code, 201, response.data)
        invitation = ExpertInvitation.objects.get()
        self.assertEqual(invitation.email, "new-expert@example.com")
        self.assertEqual(invitation.delivery_status, "sent")
        self.assertEqual(len(mail.outbox), 1)
        token = re.search(r"/expert-invitation/([\w-]+)", mail.outbox[0].body).group(1)
        self.assertEqual(invitation.token_digest, digest(token))
        self.assertNotIn(token, invitation.token_digest)
        self.assertIn("Здравствуйте!", mail.outbox[0].body)
        self.assertEqual(
            self.post(self.root + "experts/", {"email": invitation.email}).status_code,
            409,
        )
        self.program.refresh_from_db()
        self.assertTrue(self.program.is_distributed_evaluation)
        self.assertEqual(target(self.program), 2)
        self.client.force_authenticate(create_rate_user())
        self.assertEqual(self.client.get(self.root + "experts/").status_code, 403)
        self.assertEqual(
            self.post(
                self.root + "experts/", {"email": "outsider@example.com"}
            ).status_code,
            403,
        )
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.root + "experts/").status_code, 401)

    def test_new_registration_and_normal_signup_birthday_requirement(self):
        invitation, token = self.invitation()
        url = f"/evaluation/invitations/{token}/"
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertFalse(CustomUser.objects.filter(email=invitation.email).exists())
        data = dict(
            first_name="Анна",
            last_name="Волкова",
            password="SecureExpert124!",
            repeat_password="SecureExpert124!",
            accept_policy=True,
            accept_age=True,
        )
        bad = self.post(url + "register/", {**data, "accept_policy": False})
        self.assertEqual(bad.status_code, 400)
        response = self.post(url + "register/", data)
        self.assertEqual(response.status_code, 201, response.data)
        user = CustomUser.objects.get(email=invitation.email)
        self.assertIsNone(user.birthday)
        self.assertTrue(user.check_password(data["password"]))
        self.assertTrue(user.is_active)
        self.assertIsNone(user.onboarding_stage)
        self.assertTrue(user.expert.programs.filter(pk=self.program.pk).exists())
        self.assertTrue(response.data["access"])
        self.client.force_authenticate(user)
        changed = self.client.patch(
            f"/auth/users/{user.pk}/", {"first_name": "Анна"}, format="json"
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.client.force_authenticate(None)
        self.assertTrue(UserListSerializer().fields["birthday"].required)
        self.assertFalse(UserListSerializer().fields["birthday"].allow_null)
        self.assertEqual(self.post(url + "register/", data).status_code, 410)

    def test_existing_member_accepts_without_role_loss_and_wrong_account_denied(self):
        invitation, token = self.invitation(self.manager.email)
        url = f"/evaluation/invitations/{token}/accept/"
        self.client.force_authenticate(self.expert)
        self.assertEqual(self.post(url, {}).status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.post(url, {}).status_code, 200)
        self.assertEqual(self.post(url, {}).status_code, 200)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.user_type, CustomUser.MEMBER)
        self.assertTrue(self.program.managers.filter(pk=self.manager.pk).exists())
        self.assertTrue(
            Expert.objects.filter(user=self.manager, programs=self.program).exists()
        )
        # Program membership suffices without mutating the global role or registering as participant.
        self.assertEqual(
            self.client.get(f"/rate-project/{self.program.pk}").status_code, 200
        )

    def test_invitation_lifecycle_and_private_hub(self):
        invitation, token = self.invitation(self.manager.email)
        self.assertEqual(
            self.client.get("/evaluation/programs/").data["results"][0]["status"],
            "pending",
        )
        self.assertFalse(
            self.client.get("/evaluation/programs/").data["results"][0].get("assigned")
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                self.root + f"expert-invitations/{invitation.pk}/resend/", {}
            )
        self.assertEqual(response.status_code, 200)
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(f"/evaluation/invitations/{token}/").status_code, 404
        )
        current_token = re.search(
            r"/expert-invitation/([\w-]+)", mail.outbox[-1].body
        ).group(1)
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.post(
                self.root + f"expert-invitations/{invitation.pk}/revoke/", {}
            ).status_code,
            204,
        )
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(f"/evaluation/invitations/{current_token}/").status_code, 410
        )
        invitation, token = self.invitation(
            "expired@example.com", "expired-invitation-token-012345"
        )
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save()
        self.assertEqual(
            self.post(f"/evaluation/invitations/{token}/register/", {}).status_code, 410
        )

    def test_resending_old_invitation_does_not_overwrite_new_pending_one(self):
        old, _ = self.invitation("pending@example.com")
        old.status = "revoked"
        old.save()
        current, _ = self.invitation(
            "pending@example.com", "new-pending-token-0123456789"
        )
        response = self.post(self.root + f"expert-invitations/{old.pk}/resend/", {})
        self.assertEqual(response.status_code, 409)
        old.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(old.status, "revoked")
        self.assertEqual(current.status, "pending")

    def test_manual_assignment_scope_own_team_and_stale_write(self):
        url = self.root + f"experts/{self.expert.expert.pk}/assignments/"
        snapshot = self.client.get(url).data
        data = {"revision": snapshot["revision"], "project_ids": [self.project.pk]}
        response = self.client.put(url, data, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["projects"][0]["assigned"])
        self.assertEqual(self.client.put(url, data, format="json").status_code, 409)
        own = create_rate_project(leader=self.expert)
        self.program.users.add(self.expert, through_defaults={"partner_program_data": {}})
        link = link_project_to_program(self.program, own)
        link.submitted = True
        link.save()
        data = {
            "revision": self.client.get(url).data["revision"],
            "project_ids": [self.project.pk, own.pk],
        }
        self.assertEqual(self.client.put(url, data, format="json").status_code, 400)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)
        outsider = create_rate_expert(program=create_rate_program())
        self.assertEqual(
            self.client.get(
                self.root + f"experts/{outsider.expert.pk}/assignments/"
            ).status_code,
            404,
        )

    def test_auto_allocation_shortage_balance_preservation_and_conflict(self):
        self.enable()
        other = create_rate_expert(program=self.program)
        second = create_rate_project()
        self.program.users.add(
            second.leader, through_defaults={"partner_program_data": {}}
        )
        link = link_project_to_program(self.program, second)
        link.submitted = True
        link.save()
        args = {"expert_ids": [self.expert.expert.pk, other.expert.pk]}
        plan = self.post(self.root + "expert-allocation/", args)
        self.assertEqual(plan.status_code, 200, plan.data)
        self.assertEqual(len(plan.data["assignments"]), 4)
        self.assertEqual(plan.data["shortages"], [])
        apply_url = self.root + "expert-allocation/apply/"
        self.assertEqual(
            self.post(apply_url, {"plan_token": plan.data["plan_token"]}).status_code, 200
        )
        self.assertEqual(ProjectExpertAssignment.objects.count(), 4)
        self.assertEqual(
            self.post(apply_url, {"plan_token": plan.data["plan_token"]}).status_code, 409
        )
        next_plan = self.post(self.root + "expert-allocation/", args)
        self.assertEqual(next_plan.data["assignments"], [])
        self.assertEqual(
            self.post(apply_url, {"plan_token": "tampered"}).status_code, 409
        )

    @patch("project_rates.services.send_email.delay")
    def test_complete_form_scores_zero_false_optional_comment_and_protection(self, send):
        self.enable(1)
        boolean = create_rate_criteria(self.program, type="bool")
        assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=self.project, expert=self.expert.expert
        )
        self.client.force_authenticate(self.expert)
        url = f"/rate-project/rate/{self.project.pk}"
        self.assertEqual(
            self.post(
                url, [{"criterion_id": self.criterion.pk, "value": "0"}]
            ).status_code,
            400,
        )
        self.assertFalse(ProjectScore.objects.exists())
        response = self.post(
            url,
            [
                {"criterion_id": self.criterion.pk, "value": "0"},
                {"criterion_id": boolean.pk, "value": "False"},
            ],
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ProjectScore.objects.count(), self.program.criterias.count())
        self.program.refresh_from_db()
        self.assertIsNotNone(self.program.evaluation_criteria_locked_at)
        self.assertEqual(
            self.client.get("/evaluation/programs/").data["results"][0]["completed"], 1
        )
        self.client.force_authenticate(self.manager)
        assignment_url = self.root + f"experts/{self.expert.expert.pk}/assignments/"
        data = {
            "revision": self.client.get(assignment_url).data["revision"],
            "project_ids": [],
        }
        self.assertEqual(
            self.client.put(assignment_url, data, format="json").status_code, 409
        )
        self.assertTrue(ProjectExpertAssignment.objects.filter(pk=assignment.pk).exists())
        before = ProjectScore.objects.count()
        self.assertEqual(
            _solution_rows(self.program).get(pk=self.link.pk).status, "evaluated"
        )
        quota_url = self.root + "evaluators/"
        preview = self.post(quota_url, {"required_evaluators": 2}).data
        self.assertEqual(preview["ready_before"], 1)
        self.assertEqual(preview["ready_after"], 0)
        saved = self.client.put(
            quota_url,
            {"required_evaluators": 2, "revision": preview["revision"]},
            format="json",
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.program.refresh_from_db()
        self.assertEqual(
            _solution_rows(self.program).get(pk=self.link.pk).status,
            "partially_evaluated",
        )
        self.assertEqual(ProjectScore.objects.count(), before)

    def test_own_invitation_accept_and_zero_assignments_keep_menu_access(self):
        invitation, _ = self.invitation(self.manager.email)
        url = f"/evaluation/own-invitations/{invitation.pk}/accept/"
        self.assertEqual(self.post(url, {}).status_code, 200)
        hub = self.client.get("/evaluation/programs/").data
        self.assertTrue(hub["has_access"])
        self.assertEqual(hub["results"][0]["assigned"], 0)
        self.assertEqual(hub["results"][0]["status"], "joined")
        self.client.force_authenticate(create_rate_user())
        self.assertEqual(self.post(url, {}).status_code, 404)
        self.assertFalse(self.client.get("/evaluation/programs/").data["has_access"])

    def test_reset_password_preserves_invitation_and_dev_origin(self):
        invitation, token = self.invitation(self.expert.email)
        self.client.force_authenticate(None)
        response = self.post(
            "/auth/reset_password/",
            {"email": invitation.email, "expert_invitation_token": token},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(
            "https://dev.procollab.ru/auth/reset_password/?", mail.outbox[0].body
        )
        self.assertIn("expert_invitation=" + token, mail.outbox[0].body)

    def test_shortage_is_read_only_and_direct_apply_is_rejected(self):
        self.enable(3)
        plan = self.post(
            self.root + "expert-allocation/", {"expert_ids": [self.expert.expert.pk]}
        ).data
        self.assertEqual(plan["shortages"][0]["missing"], 2)
        response = self.post(
            self.root + "expert-allocation/apply/", {"plan_token": plan["plan_token"]}
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_current_profile_and_program_buttons_use_scoped_roles(self):
        invitation, token = self.invitation(self.manager.email)
        self.assertTrue(
            self.client.get("/auth/users/current/").data["has_evaluation_access"]
        )
        detail = self.client.get(f"/programs/{self.program.pk}/").data
        self.assertFalse(detail["is_user_expert"])
        self.assertEqual(detail["pending_expert_invitation_id"], invitation.pk)
        self.post(f"/evaluation/invitations/{token}/accept/", {})
        detail = self.client.get(f"/programs/{self.program.pk}/").data
        self.assertTrue(detail["is_user_expert"])
        another = create_rate_program()
        self.assertFalse(
            self.client.get(f"/programs/{another.pk}/").data["is_user_expert"]
        )

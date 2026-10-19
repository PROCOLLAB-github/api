import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import OrganizerInvitation
from project_rates.tests.helpers import create_rate_program, create_rate_user
from users.models import CustomUser, Expert


class OrganizersApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = create_rate_user()
        cls.colleague = create_rate_user(prefix="colleague")
        cls.stranger = create_rate_user(prefix="stranger")
        cls.program = create_rate_program()
        cls.program.managers.add(cls.manager)
        cls.other = create_rate_program()

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.root = f"/programs/{self.program.pk}/management/"

    def roster(self):
        return self.client.get(self.root + "organizers/").data

    def post(self, path, data):
        return self.client.post(path, data, format="json")

    def invite(self, email="new-organizer@example.com"):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                self.root + "organizers/",
                {"email": email, "revision": self.roster()["revision"]},
            )
        self.assertEqual(response.status_code, 201, response.data)
        token = re.search(
            r"/organizer-invitation/([A-Za-z0-9_-]+)", mail.outbox[-1].body
        ).group(1)
        return (
            OrganizerInvitation.objects.get(email=email.lower(), status="pending"),
            token,
        )

    def test_only_program_organizers_can_read_or_write(self):
        for user in [self.stranger, None]:
            self.client.force_authenticate(user)
            self.assertIn(
                self.client.get(self.root + "organizers/").status_code, [401, 403]
            )
            self.assertIn(
                self.post(
                    self.root + "organizers/",
                    {"email": "test@example.com", "revision": "x"},
                ).status_code,
                [401, 403],
            )
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.client.get(
                f"/programs/{self.other.pk}/management/organizers/"
            ).status_code,
            403,
        )

    def test_roster_is_private_and_last_organizer_is_protected(self):
        response = self.client.get(self.root + "organizers/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.data["organizer_count"], 1)
        self.assertFalse(response.data["organizers"][0]["can_remove"])
        self.assertTrue(response.data["organizers"][0]["is_self"])
        self.assertNotIn("token_digest", str(response.data))
        response = self.post(
            self.root + f"organizers/{self.manager.pk}/remove/",
            {"revision": response.data["revision"]},
        )
        self.assertEqual(response.status_code, 409)
        self.assertTrue(self.program.managers.filter(pk=self.manager.pk).exists())

    def test_invitation_delivers_normalized_email_without_granting_access(self):
        invitation, token = self.invite("New-Organizer@Example.com")
        invitation.refresh_from_db()
        self.assertEqual(invitation.delivery_status, "sent")
        self.assertEqual(invitation.email, "new-organizer@example.com")
        self.assertNotEqual(token, invitation.token_digest)
        self.assertEqual(self.program.managers.count(), 1)
        preview = self.client.get(f"/programs/organizer-invitations/{token}/")
        self.assertEqual(preview.data["purpose"], "organizer")
        self.assertFalse(preview.data["account_exists"])
        self.assertNotIn("token_digest", str(preview.data))
        self.assertEqual(preview["Referrer-Policy"], "no-referrer")

    def test_existing_manager_and_duplicate_pending_are_rejected(self):
        response = self.post(
            self.root + "organizers/",
            {"email": self.manager.email.upper(), "revision": self.roster()["revision"]},
        )
        self.assertEqual(response.status_code, 409)
        invitation, _ = self.invite()
        response = self.post(
            self.root + "organizers/",
            {"email": invitation.email.upper(), "revision": self.roster()["revision"]},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.program.organizer_invitations.count(), 1)

    def test_wrong_account_cannot_accept(self):
        invitation, token = self.invite(self.colleague.email)
        for user in [self.stranger, None]:
            self.client.force_authenticate(user)
            self.assertEqual(
                self.post(
                    f"/programs/organizer-invitations/{token}/accept/", {}
                ).status_code,
                403,
            )
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, "pending")

    def test_acceptance_is_explicit_idempotent_program_scoped_and_not_expert(self):
        invitation, token = self.invite(self.colleague.email)
        self.client.force_authenticate(self.colleague)
        url = f"/programs/organizer-invitations/{token}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertFalse(self.program.is_manager(self.colleague))
        self.assertEqual(self.post(url + "accept/", {}).status_code, 200)
        self.assertEqual(self.post(url + "accept/", {}).status_code, 200)
        self.assertTrue(self.program.is_manager(self.colleague))
        self.assertFalse(self.other.is_manager(self.colleague))
        self.assertFalse(Expert.objects.filter(user=self.colleague).exists())
        self.assertEqual(self.client.get(self.root + "organizers/").status_code, 200)
        self.program.refresh_from_db()
        self.assertIsNone(self.program.required_evaluators)

    def test_registration_requires_birthday_and_preserves_normal_role(self):
        _, token = self.invite()
        self.client.force_authenticate(None)
        url = f"/programs/organizer-invitations/{token}/register/"
        data = dict(
            first_name="Анна",
            last_name="Волкова",
            password="SafeOrganizer234!",
            repeat_password="SafeOrganizer234!",
            accept_policy=True,
            accept_age=True,
        )
        self.assertEqual(self.post(url, data).status_code, 400)
        data["birthday"] = "1990-01-01"
        response = self.post(url, data)
        self.assertEqual(response.status_code, 201, response.data)
        user = CustomUser.objects.get(email="new-organizer@example.com")
        self.assertTrue(user.check_password(data["password"]))
        self.assertEqual(user.birthday.isoformat(), "1990-01-01")
        self.assertTrue(self.program.is_manager(user))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.user_type, CustomUser.MEMBER)
        self.assertFalse(Expert.objects.filter(user=user).exists())
        self.assertIn("access", response.data)

    def test_registration_does_not_replace_existing_account(self):
        _, token = self.invite(self.colleague.email)
        self.client.force_authenticate(None)
        before = CustomUser.objects.count()
        self.assertEqual(
            self.post(
                f"/programs/organizer-invitations/{token}/register/", {}
            ).status_code,
            409,
        )
        self.assertEqual(CustomUser.objects.count(), before)

    def test_revoke_and_resend_invalidate_previous_links_without_duplicate_rows(self):
        invitation, token = self.invite()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                self.root + f"organizer-invitations/{invitation.pk}/resend/",
                {"revision": self.roster()["revision"]},
            )
        self.assertEqual(response.status_code, 200)
        new_token = re.search(
            r"/organizer-invitation/([A-Za-z0-9_-]+)", mail.outbox[-1].body
        ).group(1)
        self.assertNotEqual(new_token, token)
        self.assertEqual(
            self.client.get(f"/programs/organizer-invitations/{token}/").status_code, 404
        )
        self.assertEqual(OrganizerInvitation.objects.count(), 1)
        response = self.post(
            self.root + f"organizer-invitations/{invitation.pk}/revoke/",
            {"revision": self.roster()["revision"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get(f"/programs/organizer-invitations/{new_token}/").status_code,
            410,
        )
        self.assertEqual(response.data["invitation_count"], 0)

    def test_pending_or_inactive_colleague_does_not_allow_removing_last_active_manager(
        self,
    ):
        self.invite(self.colleague.email)
        self.colleague.is_active = False
        self.colleague.save()
        self.program.managers.add(self.colleague)
        response = self.post(
            self.root + f"organizers/{self.manager.pk}/remove/",
            {"revision": self.roster()["revision"]},
        )
        self.assertEqual(response.status_code, 409)

    def test_removal_revokes_access_and_previously_accepted_token(self):
        invitation, token = self.invite(self.colleague.email)
        self.client.force_authenticate(self.colleague)
        self.assertEqual(
            self.post(f"/programs/organizer-invitations/{token}/accept/", {}).status_code,
            200,
        )
        self.client.force_authenticate(self.manager)
        response = self.post(
            self.root + f"organizers/{self.colleague.pk}/remove/",
            {"revision": self.roster()["revision"]},
        )
        self.assertEqual(response.status_code, 200)
        self.client.force_authenticate(self.colleague)
        self.assertEqual(self.client.get(self.root + "organizers/").status_code, 403)
        self.assertEqual(
            self.post(f"/programs/organizer-invitations/{token}/accept/", {}).status_code,
            410,
        )
        self.assertTrue(CustomUser.objects.get(pk=self.colleague.pk).is_active)
        self.assertFalse(self.program.is_manager(self.colleague))

    def test_self_exit_returns_no_remaining_private_roster(self):
        self.program.managers.add(self.colleague)
        response = self.post(
            self.root + f"organizers/{self.manager.pk}/remove/",
            {"revision": self.roster()["revision"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["access_removed"])
        self.assertNotIn("organizers", response.data)
        self.assertEqual(self.client.get(self.root + "organizers/").status_code, 403)

    def test_stale_revision_and_foreign_member_are_rejected(self):
        old = self.roster()["revision"]
        self.program.managers.add(self.colleague)
        self.assertEqual(
            self.post(
                self.root + f"organizers/{self.manager.pk}/remove/", {"revision": old}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.post(
                self.root + f"organizers/{self.stranger.pk}/remove/",
                {"revision": self.roster()["revision"]},
            ).status_code,
            404,
        )

    def test_expired_invitation_is_gone_and_can_be_renewed(self):
        invitation, token = self.invite()
        OrganizerInvitation.objects.filter(pk=invitation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(
            self.client.get(f"/programs/organizer-invitations/{token}/").status_code, 410
        )
        self.assertEqual(self.roster()["organizers"][-1]["status"], "expired")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                self.root + f"organizer-invitations/{invitation.pk}/resend/",
                {"revision": self.roster()["revision"]},
            )
        self.assertEqual(response.status_code, 200)

    def test_broker_failure_is_visible_and_does_not_grant_access(self):
        with patch(
            "partner_programs.tasks.send_organizer_invitation.apply_async",
            side_effect=RuntimeError("broker unavailable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(
                    self.root + "organizers/",
                    {"email": "retry@example.com", "revision": self.roster()["revision"]},
                )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.roster()["organizers"][-1]["delivery_status"], "failed")
        self.assertEqual(self.program.managers.count(), 1)

    def test_invitation_name_is_resolved_by_its_email(self):
        self.colleague.first_name = "Анна"
        self.colleague.last_name = "Волкова"
        self.colleague.save()
        self.invite(self.colleague.email.upper())
        row = self.roster()["organizers"][-1]
        self.assertEqual(row["name"], "Анна Волкова")
        self.assertEqual(row["email"], self.colleague.email.lower())

    def test_reset_password_keeps_organizer_context(self):
        _, token = self.invite(self.colleague.email)
        self.client.force_authenticate(None)
        response = self.post(
            "/auth/reset_password/",
            {"email": self.colleague.email, "organizer_invitation_token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("/organizer-password-reset/?", mail.outbox[-1].body)
        self.assertIn("organizer_invitation=" + token, mail.outbox[-1].body)

    def test_organizer_token_is_redacted_from_application_logs(self):
        from core.log.utils import redact_expert_invitation_token

        token = "a" * 43
        self.assertNotIn(
            token,
            redact_expert_invitation_token(
                f"GET /programs/organizer-invitations/{token}/"
            ),
        )

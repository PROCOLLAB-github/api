from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from invites.models import Invite
from invites.serializers import InviteDetailSerializer
from invites.tests.helpers import (
    add_user_to_program,
    create_invite,
    create_project,
    create_user,
    invite_payload,
    link_project_to_program,
)
from projects import team_service
from projects.models import Collaborator


class InviteIntegrityTests(TestCase):
    def setUp(self):
        self.invite = create_invite()
        self.client = APIClient()
        self.client.force_authenticate(self.invite.user)

    def test_failure_after_collaborator_insert_rolls_back_everything(self):
        with patch.object(Invite, "save", side_effect=RuntimeError("injected")):
            with self.assertRaisesMessage(RuntimeError, "injected"):
                self.client.post(f"/invites/{self.invite.pk}/accept/")
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.is_accepted)
        self.assertFalse(
            Collaborator.objects.filter(
                project=self.invite.project, user=self.invite.user
            ).exists()
        )

    def test_membership_removed_before_accept_returns_409(self):
        program = link_project_to_program(project=self.invite.project)
        membership = add_user_to_program(user=self.invite.user, program=program)
        membership.delete()
        response = self.client.post(f"/invites/{self.invite.pk}/accept/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "not_program_member")
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.is_accepted)
        self.assertFalse(
            Collaborator.objects.filter(
                project=self.invite.project, user=self.invite.user
            ).exists()
        )

    def test_stale_serializer_cannot_restore_pending_after_accept(self):
        serializer = InviteDetailSerializer(
            self.invite,
            data={"role": "Changed"},
            partial=True,
            context={"request": SimpleNamespace(user=self.invite.project.leader)},
        )
        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            self.client.post(f"/invites/{self.invite.pk}/accept/").status_code, 200
        )
        with self.assertRaises(team_service.TeamError) as raised:
            serializer.save()
        self.assertEqual(raised.exception.detail["code"], "invite_already_processed")
        self.invite.refresh_from_db()
        self.assertIs(self.invite.is_accepted, True)
        self.assertEqual(self.invite.role, "Developer")

    def test_lifecycle_fields_cannot_be_patched(self):
        self.client.force_authenticate(self.invite.project.leader)
        response = self.client.patch(
            f"/invites/{self.invite.pk}/",
            {"is_accepted": True, "role": "Engineer"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.is_accepted)
        self.assertEqual(self.invite.role, "Engineer")

    def test_processed_invite_cannot_be_edited_or_revoked(self):
        self.client.post(f"/invites/{self.invite.pk}/decline/")
        self.client.force_authenticate(self.invite.project.leader)
        for response in (
            self.client.patch(f"/invites/{self.invite.pk}/", {"role": "Changed"}),
            self.client.delete(f"/invites/{self.invite.pk}/"),
        ):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "invite_already_processed")
        self.invite.refresh_from_db()
        self.assertIs(self.invite.is_accepted, False)

    def test_database_rejects_duplicate_pending_but_allows_history(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Проверяем именно DB guarantee, минуя более ранний model guard.
            Invite.objects.bulk_create(
                [Invite(project=self.invite.project, user=self.invite.user)]
            )
        create_invite(
            project=self.invite.project, user=self.invite.user, is_accepted=False
        )
        self.assertEqual(
            Invite.objects.filter(
                project=self.invite.project, user=self.invite.user
            ).count(),
            2,
        )

    def test_insert_constraint_conflict_maps_to_409(self):
        # Имитируем устаревший результат предварительного exists; INSERT и constraint реальные.
        pending = team_service._pending_invites(self.invite.project, self.invite.user_id)
        with patch.object(pending, "exists", side_effect=[False, True]), patch.object(
            Invite, "full_clean"
        ):
            with patch.object(team_service, "_pending_invites", return_value=pending):
                self.client.force_authenticate(self.invite.project.leader)
                response = self.client.post(
                    "/invites/", invite_payload(self.invite.project, self.invite.user)
                )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "duplicate_pending_invite")
        self.assertEqual(Invite.objects.filter(pk=self.invite.pk).count(), 1)

    def test_model_duplicate_conflict_maps_to_409(self):
        pending = team_service._pending_invites(self.invite.project, self.invite.user_id)
        with patch.object(pending, "exists", return_value=False), patch.object(
            team_service, "_pending_invites", return_value=pending
        ):
            self.client.force_authenticate(self.invite.project.leader)
            response = self.client.post(
                "/invites/", invite_payload(self.invite.project, self.invite.user)
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "duplicate_pending_invite")


@skipUnlessDBFeature("has_select_for_update")
class InviteConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.project = create_project()
        self.recipient = create_user()

    def race(self, *requests):
        barrier = Barrier(len(requests))

        def execute(actor, method, url, payload):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(actor)
                barrier.wait(timeout=10)
                response = getattr(client, method)(url, payload, format="json")
                return response.status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(execute, *request) for request in requests]
            return [future.result(timeout=20) for future in futures]

    def invite(self):
        return create_invite(project=self.project, user=self.recipient)

    def assert_consistent(self, invite_id):
        invite = Invite.objects.filter(pk=invite_id).first()
        accepted = Collaborator.objects.filter(
            project=self.project, user=self.recipient
        ).exists()
        self.assertEqual(accepted, bool(invite and invite.is_accepted is True))

    def test_concurrent_create_has_one_201_and_one_409(self):
        request = (
            self.project.leader,
            "post",
            "/invites/",
            invite_payload(self.project, self.recipient),
        )
        self.assertEqual(sorted(self.race(request, request)), [201, 409])
        self.assertEqual(Invite.objects.filter(project=self.project).count(), 1)

    def test_concurrent_double_accept_creates_one_collaborator(self):
        invite = self.invite()
        request = (self.recipient, "post", f"/invites/{invite.pk}/accept/", {})
        self.assertEqual(sorted(self.race(request, request)), [200, 409])
        self.assert_consistent(invite.pk)
        self.assertEqual(
            Collaborator.objects.filter(
                project=self.project, user=self.recipient
            ).count(),
            1,
        )

    def test_concurrent_accept_decline_has_one_winner(self):
        invite = self.invite()
        statuses = self.race(
            (self.recipient, "post", f"/invites/{invite.pk}/accept/", {}),
            (self.recipient, "post", f"/invites/{invite.pk}/decline/", {}),
        )
        self.assertEqual(sorted(statuses), [200, 409])
        self.assert_consistent(invite.pk)

    def test_concurrent_accept_revoke_has_no_partial_state(self):
        invite = self.invite()
        statuses = self.race(
            (self.recipient, "post", f"/invites/{invite.pk}/accept/", {}),
            (self.project.leader, "delete", f"/invites/{invite.pk}/", {}),
        )
        self.assertIn(statuses, ([200, 409], [404, 204]))
        self.assert_consistent(invite.pk)

    def test_concurrent_patch_accept_cannot_resurrect_pending(self):
        invite = self.invite()
        statuses = self.race(
            (self.recipient, "post", f"/invites/{invite.pk}/accept/", {}),
            (self.project.leader, "patch", f"/invites/{invite.pk}/", {"role": "New"}),
        )
        self.assertIn(statuses, ([200, 200], [200, 409]))
        self.assert_consistent(invite.pk)

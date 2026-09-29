from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from invites.models import Invite
from invites.tests.helpers import create_invite, create_project, create_user


class PendingInviteMigrationTests(TransactionTestCase):
    before = ("invites", "0002_invite_specialization")
    after = ("invites", "0003_legacy_pending_invite_constraint")

    def setUp(self):
        MigrationExecutor(connection).migrate([self.before])
        self.project = create_project()
        self.recipient = create_user()

    def tearDown(self):
        # Только fixtures этого теста: восстановить схему для остальных тестов suite.
        Invite.objects.filter(project=self.project).delete()
        MigrationExecutor(connection).migrate([self.after])
        super().tearDown()

    def test_duplicate_preflight_stops_without_choosing_a_winner(self):
        first = create_invite(project=self.project, user=self.recipient)
        second = create_invite(project=self.project, user=self.recipient)
        with self.assertRaisesMessage(RuntimeError, "without choosing a winner"):
            MigrationExecutor(connection).migrate([self.after])
        self.assertEqual(
            set(Invite.objects.filter(project=self.project).values_list("pk", flat=True)),
            {first.pk, second.pk},
        )
        self.assertEqual(
            Invite.objects.filter(project=self.project, is_accepted__isnull=True).count(),
            2,
        )

    def test_forward_backward_preserves_invites(self):
        pending = create_invite(project=self.project, user=self.recipient)
        processed = create_invite(
            project=self.project, user=self.recipient, is_accepted=False
        )
        for target in (self.after, self.before, self.after):
            MigrationExecutor(connection).migrate([target])
            pending.refresh_from_db()
            processed.refresh_from_db()
            self.assertIsNone(pending.is_accepted)
            self.assertIs(processed.is_accepted, False)

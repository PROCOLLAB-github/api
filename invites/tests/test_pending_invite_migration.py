from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from invites.tests.helpers import create_project, create_user


class PendingInviteMigrationTests(TransactionTestCase):
    before = ("invites", "0002_invite_specialization")
    after = ("invites", "0003_legacy_pending_invite_constraint")

    def setUp(self):
        executor = MigrationExecutor(connection)
        self.latest = executor.loader.graph.leaf_nodes()
        executor.migrate([self.before])
        self.Invite = executor.loader.project_state([self.before]).apps.get_model(
            "invites", "Invite"
        )
        self.project = create_project()
        self.recipient = create_user()

    def tearDown(self):
        # Только fixtures этого теста: восстановить схему для остальных тестов suite.
        self.Invite.objects.filter(project_id=self.project.pk).delete()
        MigrationExecutor(connection).migrate(self.latest)
        super().tearDown()

    def test_duplicate_preflight_stops_without_choosing_a_winner(self):
        first = self.Invite.objects.create(
            project_id=self.project.pk, user_id=self.recipient.pk
        )
        second = self.Invite.objects.create(
            project_id=self.project.pk, user_id=self.recipient.pk
        )
        with self.assertRaisesMessage(RuntimeError, "without choosing a winner"):
            MigrationExecutor(connection).migrate([self.after])
        self.assertEqual(
            set(
                self.Invite.objects.filter(project_id=self.project.pk).values_list(
                    "pk", flat=True
                )
            ),
            {first.pk, second.pk},
        )
        self.assertEqual(
            self.Invite.objects.filter(
                project_id=self.project.pk, is_accepted__isnull=True
            ).count(),
            2,
        )

    def test_forward_backward_preserves_invites(self):
        pending = self.Invite.objects.create(
            project_id=self.project.pk, user_id=self.recipient.pk
        )
        processed = self.Invite.objects.create(
            project_id=self.project.pk, user_id=self.recipient.pk, is_accepted=False
        )
        for target in (self.after, self.before, self.after):
            MigrationExecutor(connection).migrate([target])
            pending.refresh_from_db()
            processed.refresh_from_db()
            self.assertIsNone(pending.is_accepted)
            self.assertIs(processed.is_accepted, False)

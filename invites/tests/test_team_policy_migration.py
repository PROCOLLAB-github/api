from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from invites.models import Invite
from partner_programs.models import PartnerProgram
from partner_programs.tests.helpers import create_partner_program, create_program_project
from projects.tests.helpers import create_project, create_user


class TeamPolicyMigrationTests(TransactionTestCase):
    before = [
        ("invites", "0003_legacy_pending_invite_constraint"),
        ("partner_programs", "0018_partnerprogramuserprofile_welcome_acknowledged_at"),
    ]

    def test_forward_backfill_only_unique_link_and_reverse_preserves_rows(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        programs = [create_partner_program(), create_partner_program()]
        projects = [create_project() for _ in range(3)]
        one = create_program_project(programs[0], project=projects[1])
        create_program_project(programs[0], project=projects[2])
        create_program_project(programs[1], project=projects[2])
        user = create_user()
        # Fixtures до миграции: контекст тогда не существовал, model policy не вызываем.
        invites = Invite.objects.bulk_create(
            [Invite(project=project, user=user) for project in projects]
        )
        ids = [invite.pk for invite in invites]
        try:
            executor = MigrationExecutor(connection)
            executor.migrate(self.before)
            executor = MigrationExecutor(connection)
            OldInvite = executor.loader.project_state(self.before).apps.get_model(
                "invites", "Invite"
            )
            self.assertEqual(OldInvite.objects.filter(pk__in=ids).count(), 3)
            executor.migrate(latest)
            self.assertEqual(
                list(
                    Invite.objects.filter(pk__in=ids)
                    .order_by("pk")
                    .values_list("program_link_id", flat=True)
                ),
                [None, one.pk, None],
            )
            self.assertFalse(
                PartnerProgram.objects.exclude(
                    legacy_team_min_size=None, legacy_team_max_size=None
                ).exists()
            )
            MigrationExecutor(connection).migrate(self.before)
            self.assertEqual(OldInvite.objects.filter(pk__in=ids).count(), 3)
        finally:
            MigrationExecutor(connection).migrate(latest)

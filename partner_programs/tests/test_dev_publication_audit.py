import os
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
)
from partner_programs.tests.test_solution_publication import PublicationFixture
from scripts.verify_program_publication_dev import main


@skipUnless(connection.vendor == "postgresql", "DEV audit requires PostgreSQL")
class DevPublicationAuditTests(PublicationFixture, TestCase):
    def test_all_program_audit_checks_eligible_closed_and_draft_without_business_edits(self):
        self.seed_publication()
        legacy = create_partner_program(
            publish_projects_after_finish=True,
            datetime_finished=timezone.now() - timezone.timedelta(days=1),
        )
        project = create_project(is_public=False)
        draft = create_project(is_public=False, draft=True)
        create_program_project(legacy, project=project)
        create_program_project(legacy, project=draft)
        create_program_member(legacy, project=project)
        for mode in ["legacy_project", "solution"]:
            for changes in [
                dict(publish_projects_after_finish=False),
                dict(datetime_finished=timezone.now() + timezone.timedelta(days=1)),
                dict(draft=True),
            ]:
                program = create_partner_program(
                    solution_storage_mode=mode,
                    publish_projects_after_finish=True,
                    datetime_finished=timezone.now() - timezone.timedelta(days=1),
                )
                if mode == "solution":
                    self.other_solution(program)
                else:
                    create_program_project(program, project=create_project(is_public=False))
                for key, value in changes.items():
                    setattr(program, key, value)
                program.save()
        with patch.dict(os.environ, VERIFY_EXPECTED_API_SHA="a" * 40, VERIFY_PHASE="verify_publication"):
            with patch("builtins.print") as output:
                main()
        self.assertIn('"non_publication_data_unchanged": true', output.call_args.args[0])
        project.refresh_from_db()
        draft.refresh_from_db()
        self.solution.refresh_from_db()
        self.assertTrue(project.is_public)
        self.assertFalse(draft.is_public)
        self.assertIsNotNone(self.solution.published_at)

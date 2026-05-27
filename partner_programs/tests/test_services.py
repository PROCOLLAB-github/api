from django.test import TestCase
from django.utils import timezone

from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services import publish_finished_program_projects
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
)


class PublishFinishedProgramProjectsTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = create_user(prefix="publish-program-user")

    def create_program(self, **overrides):
        defaults = {
            "publish_projects_after_finish": True,
            "datetime_registration_ends": self.now - timezone.timedelta(days=5),
            "datetime_started": self.now - timezone.timedelta(days=30),
            "datetime_finished": self.now - timezone.timedelta(days=1),
        }
        defaults.update(overrides)
        return create_partner_program(**defaults)

    def create_project(self, **overrides):
        return create_project(leader=self.user, is_public=False, **overrides)

    def test_publish_updates_projects_from_both_sources(self):
        program = self.create_program()

        link_project = self.create_project(name="Linked Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=link_project,
        )

        profile_project = self.create_project(name="Profile Project")
        PartnerProgramUserProfile.objects.create(
            user=self.user,
            partner_program=program,
            project=profile_project,
            partner_program_data={},
        )

        publish_finished_program_projects()

        link_project.refresh_from_db()
        profile_project.refresh_from_db()
        self.assertTrue(link_project.is_public)
        self.assertTrue(profile_project.is_public)

    def test_publish_skips_draft_projects(self):
        program = self.create_program()
        draft_project = self.create_project(draft=True, name="Draft Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=draft_project,
        )

        publish_finished_program_projects()

        draft_project.refresh_from_db()
        self.assertFalse(draft_project.is_public)

    def test_publish_skips_when_flag_false(self):
        program = self.create_program(publish_projects_after_finish=False)
        project = self.create_project(name="Private Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )

        publish_finished_program_projects()

        project.refresh_from_db()
        self.assertFalse(project.is_public)

    def test_publish_after_flag_enabled_post_finish(self):
        program = self.create_program(publish_projects_after_finish=False)
        project = self.create_project(name="Delayed Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )

        publish_finished_program_projects()
        project.refresh_from_db()
        self.assertFalse(project.is_public)

        program.publish_projects_after_finish = True
        program.save(update_fields=["publish_projects_after_finish"])

        publish_finished_program_projects()
        project.refresh_from_db()
        self.assertTrue(project.is_public)

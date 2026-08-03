from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import Application, Submission, Team, TeamMember
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
)
from projects.models import Collaborator, Project, ProjectLink


class SubmissionProjectAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = create_user(prefix="submission-project-owner")
        self.other = create_user(prefix="submission-project-other")
        self.member = create_user(prefix="submission-project-member")
        self.inactive_member = create_user(prefix="submission-project-inactive")
        self.staff = create_user(prefix="submission-project-staff", is_staff=True)
        self.superuser = create_user(
            prefix="submission-project-superuser",
            is_staff=True,
            is_superuser=True,
        )
        self.program = create_partner_program()
        self.application = self.create_application()

    def create_application(self, **overrides):
        values = {
            "program": self.program,
            "user": self.owner,
            "created_by": self.owner,
            "status": Application.STATUS_SUBMITTED,
            "submitted_at": timezone.now(),
        }
        values.update(overrides)
        return Application.objects.create(**values)

    def create_submission(self, **overrides):
        values = {
            "application": self.application,
            "program": self.application.program,
            "submitted_by": self.application.user,
            "title": "Reusable solution",
            "description": "Submission description",
            "links": [
                "https://example.com/demo",
                "invalid-link",
                " https://example.com/demo ",
                123,
            ],
            "status": Submission.STATUS_SUBMITTED,
        }
        values.update(overrides)
        return Submission.objects.create(**values)

    def post(self, submission, user=None):
        self.client.force_authenticate(user=user or self.owner)
        return self.client.post(
            f"/submissions/{submission.pk}/project/", {}, format="json"
        )

    def test_endpoint_requires_authentication(self):
        submission = self.create_submission()
        self.client.force_authenticate(user=None)

        response = self.client.post(f"/submissions/{submission.pk}/project/")

        self.assertEqual(response.status_code, 401)

    def test_owner_creates_private_draft_project_from_submitted_submission(self):
        submission = self.create_submission()

        response = self.post(submission)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created"])
        project = Project.objects.get(pk=response.data["project"]["id"])
        self.application.refresh_from_db()
        self.assertEqual(self.application.project, project)
        self.assertEqual(project.leader, self.owner)
        self.assertEqual(project.name, submission.title)
        self.assertEqual(project.description, submission.description)
        self.assertTrue(project.draft)
        self.assertFalse(project.is_public)
        self.assertEqual(
            list(
                ProjectLink.objects.filter(project=project).values_list("link", flat=True)
            ),
            ["https://example.com/demo"],
        )

    def test_final_submission_can_create_project(self):
        submission = self.create_submission(status=Submission.STATUS_FINAL)

        response = self.post(submission)

        self.assertEqual(response.status_code, 201)

    def test_ineligible_submission_statuses_are_rejected(self):
        for index, submission_status in enumerate(
            (
                Submission.STATUS_DRAFT,
                Submission.STATUS_RETURNED,
                Submission.STATUS_CANCELLED,
            ),
            start=1,
        ):
            with self.subTest(status=submission_status):
                submission = self.create_submission(
                    status=submission_status,
                    version=index,
                )
                response = self.post(submission)
                self.assertEqual(response.status_code, 400)
        self.application.refresh_from_db()
        self.assertIsNone(self.application.project)

    def test_outsider_and_accepted_member_receive_safe_not_found(self):
        self.application.participation_mode = Application.PARTICIPATION_MODE_TEAM
        self.application.save(update_fields=["participation_mode", "updated_at"])
        submission = self.create_submission()
        team = Team.objects.create(
            application=self.application,
            captain=self.owner,
            name="Team",
        )
        TeamMember.objects.create(
            team=team,
            user=self.owner,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        TeamMember.objects.create(
            team=team,
            user=self.member,
            status=TeamMember.STATUS_ACCEPTED,
        )

        outsider_response = self.post(submission, self.other)
        member_response = self.post(submission, self.member)

        self.assertEqual(outsider_response.status_code, 404)
        self.assertEqual(member_response.status_code, 404)

    def test_staff_can_create_project(self):
        submission = self.create_submission()

        response = self.post(submission, self.staff)
        superuser_response = self.post(submission, self.superuser)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(superuser_response.status_code, 200)
        self.assertEqual(response.data["project"]["leader"]["id"], self.owner.pk)

    def test_team_project_adds_only_accepted_non_captain_members(self):
        self.application.participation_mode = Application.PARTICIPATION_MODE_TEAM
        self.application.save(update_fields=["participation_mode", "updated_at"])
        team = Team.objects.create(
            application=self.application,
            captain=self.owner,
            name="Accepted team",
        )
        TeamMember.objects.create(
            team=team,
            user=self.owner,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        TeamMember.objects.create(
            team=team,
            user=self.member,
            status=TeamMember.STATUS_ACCEPTED,
        )
        TeamMember.objects.create(
            team=team,
            user=self.inactive_member,
            status=TeamMember.STATUS_INVITED,
        )
        submission = self.create_submission()

        response = self.post(submission)

        self.assertEqual(response.status_code, 201)
        project_id = response.data["project"]["id"]
        collaborators = set(
            Collaborator.objects.filter(project_id=project_id).values_list(
                "user_id", flat=True
            )
        )
        self.assertEqual(collaborators, {self.owner.pk, self.member.pk})

    def test_individual_project_does_not_add_other_collaborators(self):
        submission = self.create_submission()

        response = self.post(submission)

        project_id = response.data["project"]["id"]
        self.assertEqual(
            list(
                Collaborator.objects.filter(project_id=project_id).values_list(
                    "user_id", flat=True
                )
            ),
            [self.owner.pk],
        )

    def test_repeated_request_and_other_version_are_idempotent(self):
        first = self.create_submission(version=1)
        second = self.create_submission(version=2, title="Newer title")

        created_response = self.post(first)
        repeated_response = self.post(first)
        other_version_response = self.post(second)

        self.assertEqual(created_response.status_code, 201)
        self.assertEqual(repeated_response.status_code, 200)
        self.assertEqual(other_version_response.status_code, 200)
        self.assertFalse(repeated_response.data["created"])
        self.assertFalse(other_version_response.data["created"])
        project_ids = {
            created_response.data["project"]["id"],
            repeated_response.data["project"]["id"],
            other_version_response.data["project"]["id"],
        }
        self.assertEqual(len(project_ids), 1)
        project = Project.objects.get(pk=project_ids.pop())
        self.assertEqual(project.name, first.title)

    def test_existing_application_project_is_returned_without_changes(self):
        existing_project = create_project(
            leader=self.owner,
            name="Existing project",
            description="Existing description",
            draft=False,
            is_public=True,
        )
        self.application.project = existing_project
        self.application.save(update_fields=["project", "updated_at"])
        submission = self.create_submission(title="Must not overwrite")

        response = self.post(submission)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["created"])
        existing_project.refresh_from_db()
        self.assertIn("Existing project", existing_project.name)
        self.assertEqual(existing_project.description, "Existing description")

    def test_one_project_can_be_reused_by_applications_in_different_programs(self):
        project = create_project(leader=self.owner, draft=True, is_public=False)
        self.application.project = project
        self.application.save(update_fields=["project", "updated_at"])
        second_program = create_partner_program()
        second_application = Application.objects.create(
            program=second_program,
            user=self.owner,
            created_by=self.owner,
            project=project,
        )

        self.assertEqual(self.application.project, second_application.project)
        self.assertEqual(project.applications.count(), 2)

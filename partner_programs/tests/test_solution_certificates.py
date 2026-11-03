"""Certificate audiences use active submitted Solution snapshots, never Project teams."""

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.certificate_models import (
    ProgramCertificate,
    ProgramCertificateBatch,
)
from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services import certificates
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_project,
    create_user,
)
from partner_programs.tests.test_solution_submission import SubmissionFixture


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SolutionCertificateAudienceTests(SubmissionFixture, TestCase):
    def setUp(self):
        self.ready()
        self.accepted = create_user()
        self.pending = create_user()
        self.registered = create_user()
        for user in (self.accepted, self.pending, self.registered):
            create_program_member(self.program, user=user)
        ProgramSolutionMember.objects.create(
            solution=self.solution, user=self.accepted, role="Разработчик"
        )
        SolutionInvitation.objects.create(
            solution=self.solution, recipient=self.pending, role="Дизайнер"
        )
        response = self.submit()
        self.assertEqual(response.status_code, 200, response.data)
        self.solution.refresh_from_db()

    def recipient_ids(self, audience="submitted"):
        return set(
            certificates.recipient_users(self.program, audience).values_list(
                "pk", flat=True
            )
        )

    def test_settings_and_audience_include_captain_and_accepted_members_once(self):
        self.assertEqual(self.recipient_ids(), {self.captain.pk, self.accepted.pk})
        registered = set(
            PartnerProgramUserProfile.objects.filter(
                partner_program=self.program, user_id__isnull=False
            ).values_list("user_id", flat=True)
        )
        self.assertEqual(self.recipient_ids("all"), registered)
        client = APIClient()
        client.force_authenticate(self.manager)
        response = client.get(f"/programs/{self.program.pk}/management/certificates/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["eligible_counts"],
            {"all": len(registered), "submitted": 2},
        )

    def test_submitted_snapshot_wins_over_changed_live_team(self):
        # Deliberate historical drift in the test database; ordinary writers are frozen.
        self.solution.members.filter(user=self.accepted).update(user=self.registered)
        self.assertEqual(self.recipient_ids(), {self.captain.pk, self.accepted.pk})

    def test_batch_initialization_uses_the_same_solution_audience_as_settings(self):
        batch = ProgramCertificateBatch.objects.create(
            program=self.program,
            snapshot=certificates.config_for(self.program).draft,
            issue_at=timezone.now(),
            public_base_url="https://dev.procollab.ru",
        )
        certificates.initialize_batch(batch.pk)
        self.assertEqual(
            set(
                ProgramCertificate.objects.filter(batch=batch).values_list(
                    "user_id", flat=True
                )
            ),
            {self.captain.pk, self.accepted.pk},
        )

    def test_draft_foreign_and_archived_solutions_do_not_supply_recipients(self):
        from partner_programs.solution_api import create_solution

        create_solution(self.program.pk, self.registered, {"name": "Черновик"})
        foreign = create_partner_program(
            name="Другая программа", solution_storage_mode="solution"
        )
        ProgramSolution.objects.filter(pk=self.solution.pk).update(program=foreign)
        self.assertEqual(self.recipient_ids(), set())
        ProgramSolution.all_objects.filter(pk=self.solution.pk).update(
            program=self.program,
            archived_at=timezone.now(),
            archived_by=self.manager,
            archive_reason="detached",
            archive_snapshot={"name": self.solution.name},
        )
        self.assertEqual(self.recipient_ids(), set())

    def test_snapshot_users_require_registration_in_the_same_program(self):
        unregistered = create_user()
        snapshot = self.solution.submission_snapshot
        snapshot["members"].append({"user": {"id": unregistered.pk}, "is_captain": False})
        ProgramSolution.objects.filter(pk=self.solution.pk).update(
            submission_snapshot=snapshot
        )
        self.assertEqual(self.recipient_ids(), {self.captain.pk, self.accepted.pk})

    def test_legacy_project_projection_never_supplies_solution_recipients(self):
        from projects.models import Collaborator

        project = create_project(leader=self.registered)
        # A historical projection is not evidence of submitting a Solution.
        PartnerProgramProject.objects.bulk_create(
            [
                PartnerProgramProject(
                    partner_program=self.program, project=project, submitted=True
                )
            ]
        )
        Collaborator.objects.bulk_create(
            [Collaborator(project=project, user=self.pending)]
        )
        self.assertEqual(self.recipient_ids(), {self.captain.pk, self.accepted.pk})

    def test_same_snapshot_member_across_submissions_gets_one_certificate(self):
        ProgramSolution.objects.create(
            program=self.program,
            captain=self.registered,
            status="submitted",
            submitted_at=timezone.now(),
            submission_snapshot={
                "captain_id": self.registered.pk,
                "members": [{"user": {"id": self.accepted.pk}, "is_captain": False}],
            },
        )
        self.assertEqual(
            list(
                certificates.recipient_users(self.program, "submitted").values_list(
                    "pk", flat=True
                )
            ),
            sorted([self.captain.pk, self.accepted.pk, self.registered.pk]),
        )

import copy

from django.test import TestCase

from partner_programs.solution_models import ProgramSolutionMember
from partner_programs.tests.helpers import create_program_member, create_user
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_submission import SubmissionFixture
from project_rates.solution_models import SolutionExpertAssignment
from project_rates.tests.helpers import create_rate_expert


class SolutionAccessBoundaryTests(SubmissionFixture, TestCase):
    def setUp(self):
        self.ready()
        self.member = create_user()
        create_program_member(self.program, user=self.member)
        ProgramSolutionMember.objects.create(solution=self.solution, user=self.member)
        self.expert = create_rate_expert(program=self.program)
        self.outsider = create_user()

    def state(self):
        self.solution.refresh_from_db()
        return copy.deepcopy(
            {
                "name": self.solution.name,
                "status": self.solution.status,
                "version": self.solution.version,
                "updated_at": self.solution.updated_at,
                "submitted_at": self.solution.submitted_at,
                "snapshot": self.solution.submission_snapshot,
                "answers": list(self.solution.answers.order_by("pk").values()),
                "members": list(self.solution.members.order_by("pk").values()),
            }
        )

    def assert_denied(self, actor, status, code):
        before = self.state()
        command = self.command()
        for method, url, body in (
            (
                "patch",
                self.url,
                {
                    **command,
                    "name": "Чужая правка",
                    "answers": [{"field_id": self.fields["number"]["id"], "value": 42}],
                },
            ),
            ("post", self.submit_url, command),
        ):
            with self.subTest(method=method, actor=actor.pk):
                self.assert_error(call(actor, method, url, body), code, status)
                self.assertEqual(self.state(), before)

    def test_draft_member_cannot_write_and_expert_and_outsider_cannot_discover_it(self):
        for actor in (self.captain, self.member):
            self.assertEqual(call(actor, "get", self.url).status_code, 200)
        self.assert_denied(self.member, 403, "not_solution_captain")
        for actor in (self.expert, self.outsider):
            self.assert_error(call(actor, "get", self.url), "not_found", 404)
            self.assert_denied(actor, 404, "not_found")

    def test_assigned_expert_can_read_submitted_but_cannot_write_or_submit(self):
        self.assertEqual(self.submit().status_code, 200)
        self.program.is_distributed_evaluation = True
        self.program.save()
        SolutionExpertAssignment.objects.create(
            partner_program=self.program,
            solution=self.solution,
            expert=self.expert.expert,
        )
        for actor in (self.member, self.expert):
            result = call(actor, "get", self.url)
            self.assertEqual(result.status_code, 200, result.data)
            self.assertFalse(result.data["permissions"]["can_edit"])
            self.assertFalse(result.data["permissions"]["can_submit"])
            self.assert_denied(actor, 403, "not_solution_captain")
        self.assert_denied(self.outsider, 404, "not_found")

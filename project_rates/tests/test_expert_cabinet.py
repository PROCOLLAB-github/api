from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)
from projects.models import Collaborator


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ExpertCabinetTests(TestCase):
    def setUp(self):
        self.program = create_rate_program(
            is_competitive=True,
            is_distributed_evaluation=True,
            required_evaluators=1,
            datetime_evaluation_ends=timezone.now() + timedelta(days=2),
        )
        self.user = create_rate_expert(program=self.program)
        self.criterion = create_rate_criteria(self.program)
        self.project, self.link, self.assignment = self.assign(self.program, "A project")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def assign(self, program, name, **options):
        project = create_rate_project(name=name, **options)
        program.users.add(project.leader, through_defaults={"partner_program_data": {}})
        link = link_project_to_program(program, project)
        link.submitted = True
        link.save()
        assignment = ProjectExpertAssignment.objects.create(
            partner_program=program, project=project, expert=self.user.expert
        )
        return project, link, assignment

    def page(self, **query):
        response = self.client.get(
            "/evaluation/programs/", {"include": "projects", **query}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.data["projects"]

    def complete(self, program, project):
        for criterion in program.criterias.all():
            ProjectScore.objects.create(
                project=project,
                criteria=criterion,
                user=self.user,
                value={"int": "0", "bool": "False", "str": ""}[criterion.type],
            )

    def test_existing_programs_contract_is_unchanged_without_include(self):
        data = self.client.get("/evaluation/programs/").data
        self.assertEqual(set(data), {"results", "has_access"})
        self.assertEqual(data["results"][0]["assigned"], 1)
        self.assertEqual(data["results"][0]["remaining"], 1)

    def test_only_current_membership_and_own_assignments_are_visible(self):
        outsider = create_rate_expert(program=self.program)
        other_project = create_rate_project(name="Foreign assignment")
        self.program.users.add(
            other_project.leader, through_defaults={"partner_program_data": {}}
        )
        link_project_to_program(self.program, other_project)
        ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=other_project, expert=outsider.expert
        )
        rows = self.page()["results"]
        self.assertEqual([r["project_id"] for r in rows], [self.project.pk])
        self.user.expert.programs.remove(self.program)
        self.assertEqual(self.page()["count"], 0)

    def test_foreign_program_filter_does_not_reveal_program_or_projects(self):
        foreign = create_rate_program()
        data = self.page(program_id=foreign.pk)
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])
        self.assertEqual(data["pending"], 1)
        self.client.force_authenticate(create_rate_user())
        self.assertEqual(self.page()["results"], [])
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get("/evaluation/programs/?include=projects").status_code, 401
        )

    def test_zero_and_non_numeric_answers_complete_using_existing_rule(self):
        create_rate_criteria(self.program, type="bool")
        self.complete(self.program, self.project)
        self.assertEqual(self.page()["pending"], 0)
        done = self.page(status="completed")
        self.assertEqual(done["completed"], 1)
        self.assertTrue(done["results"][0]["is_completed"])
        self.assertNotIn("in_progress", str(done))

    def test_programs_sharing_project_do_not_mix_scores_or_completion(self):
        other = create_rate_program(datetime_evaluation_ends=None)
        self.user.expert.programs.add(other)
        create_rate_criteria(other)
        other.users.add(
            self.project.leader, through_defaults={"partner_program_data": {}}
        )
        # Persisted legacy shared applications predate the current team freeze.
        PartnerProgramProject.objects.bulk_create(
            [
                PartnerProgramProject(
                    partner_program=other, project=self.project, submitted=True
                )
            ]
        )
        ProjectExpertAssignment.objects.create(
            partner_program=other, project=self.project, expert=self.user.expert
        )
        self.complete(other, self.project)
        pending = self.page()
        self.assertEqual(pending["pending"], 1)
        self.assertEqual(pending["completed"], 1)
        self.assertEqual(pending["results"][0]["program_id"], self.program.pk)
        done = self.page(status="completed")
        self.assertEqual(done["results"][0]["program_id"], other.pk)

    def test_completion_does_not_require_numeric_criteria(self):
        self.criterion.delete()
        create_rate_criteria(self.program, type="bool")
        self.complete(self.program, self.project)
        self.assertEqual(self.page()["pending"], 0)
        self.assertEqual(self.page(status="completed")["completed"], 1)

    def test_draft_and_unlinked_assignments_do_not_disclose_project_data(self):
        self.assign(self.program, "Private draft", draft=True)
        _, link, _ = self.assign(self.program, "Unlinked project")
        # Deliberate historical orphan: normal submitted applications cannot detach here.
        PartnerProgramProject.objects.filter(pk=link.pk).delete()
        page = self.page()
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["unavailable"], 2)
        self.assertNotIn("Private draft", str(page))
        self.assertNotIn("Unlinked project", str(page))

    def test_case_is_program_field_and_stale_values_are_not_guessed(self):
        field = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="case",
            label="Кейс",
            field_type="select",
            options="Case A|Case B",
            is_required=True,
            show_filter=True,
        )
        # Historical persisted value; normal writes freeze after submission.
        value = PartnerProgramFieldValue(
            field=field, program_project=self.link, value_text="Case A"
        )
        PartnerProgramFieldValue.objects.bulk_create([value])
        self.assertEqual(self.page()["results"][0]["case_name"], "Case A")
        PartnerProgramFieldValue.objects.filter(pk=value.pk).update(value_text="old")
        self.assertIsNone(self.page()["results"][0]["case_name"])

    def test_search_pagination_and_counters_are_not_limited_to_first_page(self):
        for index in range(25):
            self.assign(self.program, f"Project {index:02}")
        first, second = self.page(), self.page(offset=20)
        self.assertEqual(first["limit"], 20)
        self.assertEqual(len(first["results"]), 20)
        self.assertEqual(len(second["results"]), 6)
        self.assertEqual(first["count"], 26)
        self.assertFalse(
            {r["assignment_id"] for r in first["results"]}
            & {r["assignment_id"] for r in second["results"]}
        )
        filtered = self.page(q="Project 24")
        self.assertEqual(filtered["count"], 1)
        self.assertEqual(filtered["pending"], 26)

    def test_deadlines_sort_first_without_deadline_last(self):
        for days in (None, 1, 5):
            program = create_rate_program(
                is_competitive=True,
                datetime_evaluation_ends=(
                    timezone.now() + timedelta(days=days) if days else None
                ),
            )
            self.user.expert.programs.add(program)
            self.assign(program, f"Deadline {days}")
        self.assertEqual(
            [r["name"].split()[1] for r in self.page()["results"]],
            ["1", "project", "5", "None"],
        )

    def test_actual_scoring_constraints_are_exposed_without_new_states(self):
        # Exercise historical unsent assignments without changing the submission policy.
        PartnerProgramProject.objects.filter(pk=self.link.pk).update(submitted=False)
        self.assertEqual(
            self.page()["results"][0]["blocked_reason"], "Решение еще не сдано"
        )
        PartnerProgramProject.objects.filter(pk=self.link.pk).update(submitted=True)
        Collaborator.objects.bulk_create(
            [Collaborator(project=self.project, user=self.user)]
        )
        self.assertFalse(self.page()["results"][0]["can_rate"])
        self.program.datetime_evaluation_ends = timezone.now() - timedelta(seconds=1)
        self.program.save()
        self.assertEqual(
            self.page()["results"][0]["blocked_reason"], "Срок оценивания завершен"
        )
        self.program.datetime_evaluation_ends = None
        self.program.save()
        self.program.criterias.all().delete()
        self.assertEqual(
            self.page()["results"][0]["blocked_reason"], "Критерии не настроены"
        )

    def test_legacy_limit_keeps_existing_raters_eligible(self):
        self.program.required_evaluators = None
        self.program.max_project_rates = 1
        self.program.save()
        other = create_rate_expert(program=self.program)
        ProjectScore.objects.create(
            project=self.project, criteria=self.criterion, user=other, value="1"
        )
        self.assertEqual(
            self.page()["results"][0]["blocked_reason"], "Лимит оценок достигнут"
        )
        self.complete(self.program, self.project)
        self.assertTrue(self.page(status="completed")["results"][0]["can_rate"])

    def test_invalid_query_is_rejected(self):
        for query in (
            {"status": "started"},
            {"limit": 101},
            {"offset": -1},
            {"program_id": 0},
            {"q": "x" * 201},
        ):
            with self.subTest(query=query):
                response = self.client.get(
                    "/evaluation/programs/", {"include": "projects", **query}
                )
                self.assertEqual(response.status_code, 400)

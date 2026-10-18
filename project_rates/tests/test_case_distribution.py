"""Case eligibility, universal workload and atomic project-centric assignment."""

from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramField, PartnerProgramFieldValue
from project_rates.models import ExpertCaseScope, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_user,
    create_rate_expert,
    create_rate_project,
    link_project_to_program,
    create_rate_criteria,
)


class CaseDistributionTests(TestCase):
    def test_inactive_existing_expert_can_be_kept_but_not_newly_assigned(self):
        self.assertEqual(self.write(self.projects[:1], [self.universal]).status_code, 200)
        type(self.universal).objects.filter(pk=self.universal.pk).update(is_active=False)
        self.assertEqual(
            self.write(
                self.projects[:1], [self.universal, self.sber], mode="replace"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.write(self.projects[1:2], [self.universal]).status_code, 400
        )

    def setUp(self):
        self.manager = create_rate_user()
        self.program = create_rate_program(
            required_evaluators=2, is_distributed_evaluation=True
        )
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.root = f"/programs/{self.program.pk}/management/"
        self.field = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="case",
            label="Кейс",
            field_type="select",
            is_required=True,
            show_filter=True,
            options="Сбер|Т-Банк",
        )
        self.universal = create_rate_expert(program=self.program)
        self.sber = create_rate_expert(program=self.program)
        self.bank = create_rate_expert(program=self.program)
        self.projects = [
            self.project(name) for name in ["Сбер", "Сбер", "Т-Банк", "Т-Банк"]
        ]
        self.scope(self.sber, ["Сбер"])
        self.scope(self.bank, ["Т-Банк"])

    def project(self, case, **kwargs):
        project = create_rate_project(**kwargs)
        self.program.users.add(
            project.leader, through_defaults={"partner_program_data": {}}
        )
        link = link_project_to_program(self.program, project)
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=self.field, value_text=case
        )
        type(link).objects.filter(pk=link.pk).update(submitted=True)
        return project

    def scope(self, user, names):
        ExpertCaseScope.objects.update_or_create(
            partner_program=self.program,
            expert=user.expert,
            defaults={"all_cases": False, "case_names": names},
        )

    def state(self):
        response = self.client.get(self.root + "experts/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def write(self, projects, experts, **overrides):
        return self.client.post(
            self.root + "project-experts/",
            {
                "revision": self.state()["revision"],
                "project_ids": [p.pk for p in projects],
                "expert_ids": [u.expert.pk for u in experts],
                "mode": "add",
                **overrides,
            },
            format="json",
        )

    def plan(self, **overrides):
        return self.client.post(
            self.root + "expert-allocation/",
            {
                "expert_ids": [
                    u.expert.pk for u in [self.sber, self.bank, self.universal]
                ],
                "case_pools": [
                    {
                        "case_name": "Сбер",
                        "expert_ids": [self.sber.expert.pk, self.universal.expert.pk],
                    },
                    {
                        "case_name": "Т-Банк",
                        "expert_ids": [self.bank.expert.pk, self.universal.expert.pk],
                    },
                ],
                **overrides,
            },
            format="json",
        )

    def test_workspace_contains_cases_scopes_and_project_assignments(self):
        self.assertEqual(self.write(self.projects[:1], [self.sber]).status_code, 200)
        state = self.state()
        self.assertEqual(state["cases"], ["Сбер", "Т-Банк"])
        self.assertEqual(len(state["projects"]), 4)
        row = next(e for e in state["experts"] if e["id"] == self.universal.expert.pk)
        self.assertTrue(row["all_cases"])
        project = state["projects"][0]
        self.assertEqual(project["case_name"], "Сбер")
        self.assertFalse(project["experts"][0]["completed"])

    def test_scope_save_supports_multiple_cases_and_rejects_foreign_case(self):
        url = self.root + f"experts/{self.sber.expert.pk}/cases/"
        data = {
            "revision": self.state()["revision"],
            "all_cases": False,
            "case_names": ["Сбер", "Т-Банк"],
        }
        response = self.client.put(url, data, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            ExpertCaseScope.objects.get(expert=self.sber.expert).case_names,
            ["Сбер", "Т-Банк"],
        )
        data.update(revision=self.state()["revision"], case_names=["Чужой кейс"])
        self.assertEqual(self.client.put(url, data, format="json").status_code, 400)

    def test_manual_and_legacy_assignment_reject_expert_from_other_case(self):
        self.assertEqual(self.write(self.projects[:1], [self.bank]).status_code, 400)
        response = self.client.put(
            self.root + f"experts/{self.bank.expert.pk}/assignments/",
            {"revision": self.state()["revision"], "project_ids": [self.projects[0].pk]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_bulk_add_preserves_existing_experts_and_is_idempotent(self):
        self.assertEqual(self.write(self.projects[:1], [self.universal]).status_code, 200)
        self.assertEqual(self.write(self.projects[:2], [self.sber]).status_code, 200)
        self.assertEqual(self.write(self.projects[:2], [self.sber]).status_code, 200)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 3)

    def test_bulk_different_cases_rejected_without_partial_writes(self):
        self.assertEqual(
            self.write(
                [self.projects[0], self.projects[2]], [self.universal]
            ).status_code,
            400,
        )
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_own_team_prevents_entire_bulk_write(self):
        project = self.project("Сбер", leader=self.universal)
        self.assertEqual(
            self.write([self.projects[0], project], [self.universal]).status_code, 400
        )
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_replacement_protects_saved_scores_but_allows_removing_unscored(self):
        self.assertEqual(
            self.write(self.projects[:1], [self.sber, self.universal]).status_code, 200
        )
        criterion = create_rate_criteria(self.program)
        ProjectScore.objects.create(
            criteria=criterion, project=self.projects[0], user=self.sber, value="1"
        )
        result = self.write(self.projects[:1], [self.universal], mode="replace")
        self.assertEqual(result.status_code, 409)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 2)
        self.assertEqual(
            self.write(self.projects[:1], [self.sber], mode="replace").status_code, 200
        )
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)

    def test_changed_case_scope_preserves_assignments_and_invalidates_plan(self):
        self.assertEqual(self.write(self.projects[:1], [self.sber]).status_code, 200)
        plan = self.plan().data
        self.scope(self.universal, ["Сбер"])
        result = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": plan["plan_token"]},
            format="json",
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)

    def test_changed_project_case_invalidates_plan(self):
        plan = self.plan().data
        PartnerProgramFieldValue.objects.filter(
            program_project__project=self.projects[0]
        ).update(value_text="Т-Банк")
        result = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": plan["plan_token"]},
            format="json",
        )
        self.assertEqual(result.status_code, 409)
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_overlapping_pools_count_universal_workload_once(self):
        result = self.plan()
        self.assertEqual(result.status_code, 200, result.data)
        plan = result.data
        self.assertFalse(plan["shortages"])
        self.assertEqual(len(plan["assignments"]), 8)
        universal = [
            r for r in plan["load"] if r["expert_id"] == self.universal.expert.pk
        ]
        self.assertEqual(len(universal), 1)
        self.assertEqual(universal[0]["after"], 4)
        for row in plan["assignments"]:
            if row["case_name"] == "Сбер":
                self.assertNotEqual(row["expert_id"], self.bank.expert.pk)
            else:
                self.assertNotEqual(row["expert_id"], self.sber.expert.pk)
        self.assertFalse(ProjectExpertAssignment.objects.exists())
        applied = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": plan["plan_token"]},
            format="json",
        )
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 8)
        self.assertEqual(
            len(
                {
                    (a.project_id, a.expert_id)
                    for a in ProjectExpertAssignment.objects.all()
                }
            ),
            8,
        )

    def test_shortage_when_pool_is_empty_blocks_all_application(self):
        result = self.plan(case_pools=[{"case_name": "Сбер", "expert_ids": []}])
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(len(result.data["shortages"]), 4)
        applied = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": result.data["plan_token"]},
            format="json",
        )
        self.assertEqual(applied.status_code, 409)
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_reject_pool_outside_eligibility_and_nonmember(self):
        response = self.plan(
            case_pools=[{"case_name": "Сбер", "expert_ids": [self.bank.expert.pk]}]
        )
        self.assertEqual(response.status_code, 400)
        outsider = create_rate_expert()
        self.assertEqual(self.write(self.projects[:1], [outsider]).status_code, 400)

    def test_stale_project_write_preserves_assignments(self):
        old = self.state()["revision"]
        self.write(self.projects[:1], [self.sber])
        response = self.write(self.projects[:1], [self.universal], revision=old)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)

    def test_scope_and_assignment_endpoints_require_program_manager(self):
        self.client.force_authenticate(create_rate_user())
        self.assertEqual(self.client.get(self.root + "experts/").status_code, 403)
        self.assertEqual(
            self.client.post(
                self.root + "project-experts/",
                {"revision": "x", "project_ids": [self.projects[0].pk], "expert_ids": []},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.put(
                self.root + f"experts/{self.sber.expert.pk}/cases/",
                {"revision": "x", "all_cases": True, "case_names": []},
                format="json",
            ).status_code,
            403,
        )

    def test_draft_unsubmitted_and_foreign_projects_cannot_be_assigned(self):
        for update in [{"draft": True}, {"draft": False}]:
            type(self.projects[0]).objects.filter(pk=self.projects[0].pk).update(**update)
            if not update["draft"]:
                self.program.program_projects.filter(project=self.projects[0]).update(
                    submitted=False
                )
            self.assertEqual(
                self.write(self.projects[:1], [self.universal]).status_code, 400
            )
        self.assertEqual(
            self.write([create_rate_project()], [self.universal]).status_code, 400
        )

    def test_scope_from_other_program_does_not_restrict_expert_here(self):
        other = create_rate_program()
        ExpertCaseScope.objects.create(
            partner_program=other,
            expert=self.universal.expert,
            all_cases=False,
            case_names=[],
        )
        self.assertEqual(self.write(self.projects[:1], [self.universal]).status_code, 200)

    def test_scopes_survive_refresh_and_default_all_covers_new_cases(self):
        self.field.options += "|Новый"
        self.field.save()
        project = self.project("Новый")
        self.assertEqual(self.write([project], [self.universal]).status_code, 200)
        self.assertEqual(self.write([project], [self.sber]).status_code, 400)

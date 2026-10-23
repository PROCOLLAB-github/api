"""Case eligibility, universal workload and atomic project-centric assignment."""

from django.test import TestCase
from django.core import signing
from unittest.mock import patch
import time
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramField, PartnerProgramFieldValue
from project_rates.models import (
    Criteria,
    ExpertCaseScope,
    ProjectExpertAssignment,
    ProjectScore,
)
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_user,
    create_rate_expert,
    create_rate_project,
    link_project_to_program,
    create_rate_criteria,
)


class CaseDistributionTests(TestCase):
    def test_load_separates_assigned_projects_from_completed_work(self):
        self.write(self.projects[:1], [self.universal, self.sber])
        create_rate_criteria(self.program)
        for criterion in Criteria.objects.filter(partner_program=self.program):
            ProjectScore.objects.create(
                criteria=criterion,
                project=self.projects[0],
                user=self.universal,
                value="1",
            )
        result = self.plan(project_ids=[self.projects[0].pk])
        self.assertEqual(result.status_code, 200, result.data)
        row = next(
            r for r in result.data["load"] if r["expert_id"] == self.universal.expert.pk
        )
        self.assertEqual((row["assigned_before"], row["assigned_after"]), (1, 1))
        self.assertEqual((row["before"], row["after"]), (0, 0))

    def test_repeated_alternative_never_repeats_previous_even_with_same_seed(self):
        users = [self.universal] + [
            create_rate_expert(program=self.program) for _ in range(3)
        ]
        ids = [u.expert.pk for u in users]
        query = {
            "expert_ids": ids,
            "case_pools": [
                {"case_name": c, "expert_ids": ids} for c in ["Сбер", "Т-Банк"]
            ],
            "seed": 0,
        }
        response = self.plan(**query)
        self.assertEqual(response.status_code, 200)
        for _ in range(6):
            previous = response.data
            self.assertTrue(previous["can_reroll"])
            response = self.plan(**query, previous_plan_token=previous["plan_token"])
            self.assertEqual(response.status_code, 200, response.data)
            previous_pairs = {
                (r["project_id"], r["expert_id"]) for r in previous["assignments"]
            }
            current_pairs = {
                (r["project_id"], r["expert_id"]) for r in response.data["assignments"]
            }
            self.assertNotEqual(previous_pairs, current_pairs)
            self.assertEqual(len(current_pairs), 8)
            self.assertLessEqual(
                sum(r["after"] ** 2 for r in response.data["load"]),
                sum(r["after"] ** 2 for r in previous["load"]),
            )
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_unique_plan_does_not_offer_alternative(self):
        first = self.plan().data
        self.assertFalse(first["can_reroll"])
        response = self.plan(previous_plan_token=first["plan_token"])
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_previous_plan_rejects_tampering_foreign_program_expiry_and_changed_pools(
        self,
    ):
        first = self.plan().data
        payload = signing.loads(first["plan_token"], salt="expert-allocation")
        foreign = signing.dumps(
            {**payload, "program_id": self.program.pk + 1000}, salt="expert-allocation"
        )
        self.assertEqual(self.plan(previous_plan_token=foreign).status_code, 400)
        self.assertEqual(
            self.plan(previous_plan_token=first["plan_token"] + "broken").status_code, 409
        )
        later = time.time() + 901
        with patch("django.core.signing.time.time", return_value=later):
            self.assertEqual(
                self.plan(previous_plan_token=first["plan_token"]).status_code, 409
            )
        self.assertEqual(
            self.plan(
                previous_plan_token=first["plan_token"],
                case_pools=[{"case_name": "Сбер", "expert_ids": []}],
            ).status_code,
            400,
        )
        self.write(self.projects[:1], [self.sber])
        self.assertEqual(
            self.plan(previous_plan_token=first["plan_token"]).status_code, 409
        )

    def test_seed_varies_equal_load_choices_without_changing_existing_assignments(self):
        self.write(self.projects[:1], [self.universal])
        extra = [create_rate_expert(program=self.program) for _ in range(3)]
        ids = [u.expert.pk for u in [self.universal, *extra]]
        variants = set()
        for seed in range(8):
            response = self.plan(
                expert_ids=ids,
                project_ids=[self.projects[0].pk],
                case_pools=[{"case_name": "Сбер", "expert_ids": ids}],
                seed=seed,
            )
            self.assertEqual(response.status_code, 200, response.data)
            rows = response.data["assignments"]
            self.assertEqual(len(rows), 1)  # one existing + one proposed = two
            self.assertNotEqual(rows[0]["expert_id"], self.universal.expert.pk)
            variants.add(rows[0]["expert_id"])
        self.assertGreater(len(variants), 1)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)

    def test_override_is_preview_only_then_applies_with_the_signed_plan(self):
        ids = [self.sber.expert.pk, self.universal.expert.pk]
        response = self.plan(
            assignment_overrides=[{"project_id": self.projects[0].pk, "expert_ids": ids}]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {
                r["expert_id"]
                for r in response.data["assignments"]
                if r["project_id"] == self.projects[0].pk
            },
            set(ids),
        )
        self.assertFalse(ProjectExpertAssignment.objects.exists())
        applied = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": response.data["plan_token"]},
            format="json",
        )
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 8)

    def test_override_rejects_wrong_pool_own_team_duplicates_and_foreign_project(self):
        own = self.project("Сбер", leader=self.universal)
        foreign = create_rate_project()
        rows = [
            [{"project_id": self.projects[0].pk, "expert_ids": [self.bank.expert.pk]}],
            [{"project_id": own.pk, "expert_ids": [self.universal.expert.pk]}],
            [{"project_id": foreign.pk, "expert_ids": []}],
            [
                {
                    "project_id": self.projects[0].pk,
                    "expert_ids": [self.sber.expert.pk] * 2,
                }
            ],
            [{"project_id": self.projects[0].pk, "expert_ids": []}] * 2,
        ]
        for overrides in rows:
            with self.subTest(overrides=overrides):
                self.assertEqual(
                    self.plan(assignment_overrides=overrides).status_code, 400
                )
        self.assertFalse(ProjectExpertAssignment.objects.exists())

    def test_override_cannot_exceed_free_slots_or_repeat_an_existing_expert(self):
        self.write(self.projects[:1], [self.universal])
        for ids in [
            [self.universal.expert.pk],
            [self.sber.expert.pk, self.universal.expert.pk],
        ]:
            self.assertEqual(
                self.plan(
                    assignment_overrides=[
                        {"project_id": self.projects[0].pk, "expert_ids": ids}
                    ]
                ).status_code,
                400,
            )
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)

    def test_underfilled_override_blocks_apply_and_stale_override_is_rejected(self):
        old = self.state()["revision"]
        response = self.plan(
            assignment_overrides=[{"project_id": self.projects[0].pk, "expert_ids": []}]
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["shortages"])
        self.assertEqual(
            self.client.post(
                self.root + "expert-allocation/apply/",
                {"plan_token": response.data["plan_token"]},
                format="json",
            ).status_code,
            409,
        )
        self.write(self.projects[:1], [self.sber])
        self.assertEqual(
            self.plan(revision=old, assignment_overrides=[]).status_code, 409
        )

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

    def test_manual_add_rejects_expert_beyond_quota(self):
        self.assertEqual(
            self.write(self.projects[:1], [self.sber, self.universal]).status_code, 200
        )
        extra = create_rate_expert(program=self.program)
        response = self.write(self.projects[:1], [extra])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "expert_limit_reached")
        self.assertEqual(ProjectExpertAssignment.objects.count(), 2)

    def test_replace_unscored_at_quota_preserves_other_experts_grade(self):
        self.write(self.projects[:1], [self.sber, self.universal])
        score = ProjectScore.objects.create(
            criteria=create_rate_criteria(self.program),
            project=self.projects[0],
            user=self.sber,
            value="1",
        )
        extra = create_rate_expert(program=self.program)
        rejected = self.write(
            self.projects[:1], [self.sber, self.universal, extra], mode="replace"
        )
        self.assertEqual(rejected.status_code, 409, rejected.data)
        result = self.write(self.projects[:1], [self.sber, extra], mode="replace")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(
            set(ProjectExpertAssignment.objects.values_list("expert_id", flat=True)),
            {self.sber.expert.pk, extra.expert.pk},
        )
        score.refresh_from_db()
        self.assertEqual(score.value, "1")

    def test_bulk_exceeding_one_projects_limit_is_fully_rolled_back(self):
        self.write(self.projects[:1], [self.sber, self.universal])
        extra = create_rate_expert(program=self.program)
        response = self.write(self.projects[:2], [extra])
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 2)
        self.assertFalse(
            ProjectExpertAssignment.objects.filter(project=self.projects[1]).exists()
        )

    def test_legacy_manual_endpoint_cannot_bypass_project_limit(self):
        self.write(self.projects[:1], [self.sber, self.universal])
        extra = create_rate_expert(program=self.program)
        response = self.client.put(
            self.root + f"experts/{extra.expert.pk}/assignments/",
            {"revision": self.state()["revision"], "project_ids": [self.projects[0].pk]},
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "expert_limit_reached")
        self.assertEqual(ProjectExpertAssignment.objects.count(), 2)

    def test_lower_quota_preserves_surplus_and_allows_only_unscored_removals(self):
        self.write(self.projects[:1], [self.sber, self.universal])
        score = ProjectScore.objects.create(
            criteria=create_rate_criteria(self.program),
            project=self.projects[0],
            user=self.sber,
            value="1",
        )
        response = self.client.put(
            self.root + "evaluators/",
            {"revision": self.state()["revision"], "required_evaluators": 1},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 2)
        self.assertEqual(
            self.write(
                self.projects[:1], [self.sber, self.universal], mode="replace"
            ).status_code,
            200,
        )
        extra = create_rate_expert(program=self.program)
        self.assertEqual(
            self.write(self.projects[:1], [self.sber, extra], mode="replace").status_code,
            409,
        )
        self.assertEqual(
            self.write(self.projects[:1], [self.universal], mode="replace").status_code,
            409,
        )
        self.assertEqual(
            self.write(self.projects[:1], [self.sber], mode="replace").status_code, 200
        )
        self.assertEqual(ProjectExpertAssignment.objects.count(), 1)
        self.assertTrue(ProjectScore.objects.filter(pk=score.pk).exists())

    def test_historical_grade_counts_towards_limit_when_enabling_workspace(self):
        self.program.required_evaluators = None
        self.program.max_project_rates = 1
        self.program.save()
        score = ProjectScore.objects.create(
            criteria=create_rate_criteria(self.program),
            project=self.projects[0],
            user=self.sber,
            value="1",
        )
        response = self.write(self.projects[:1], [self.universal])
        self.assertEqual(response.status_code, 409, response.data)
        self.program.refresh_from_db()
        self.assertIsNone(self.program.required_evaluators)
        self.assertFalse(ProjectExpertAssignment.objects.exists())
        self.assertTrue(ProjectScore.objects.filter(pk=score.pk).exists())

    def test_auto_does_not_add_to_project_at_quota(self):
        self.write(self.projects[:1], [self.sber, self.universal])
        response = self.plan(project_ids=[self.projects[0].pk])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["assignments"], [])
        applied = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": response.data["plan_token"]},
            format="json",
        )
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertEqual(ProjectExpertAssignment.objects.count(), 2)

    def test_auto_apply_rechecks_limit_after_restoring_historical_assignments(self):
        self.program.required_evaluators = None
        self.program.max_project_rates = 1
        self.program.save()
        ProjectScore.objects.create(
            criteria=create_rate_criteria(self.program),
            project=self.projects[0],
            user=self.sber,
            value="1",
        )
        response = self.plan(project_ids=[self.projects[0].pk])
        self.assertEqual(response.status_code, 200, response.data)
        applied = self.client.post(
            self.root + "expert-allocation/apply/",
            {"plan_token": response.data["plan_token"]},
            format="json",
        )
        self.assertEqual(applied.status_code, 409, applied.data)
        self.assertFalse(ProjectExpertAssignment.objects.exists())

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

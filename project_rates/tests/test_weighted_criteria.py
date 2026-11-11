from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APIClient

from partner_programs.services.results_excel import export_results
from project_rates.evaluation_math import evaluation_totals
from project_rates.models import Criteria, ProjectScore
from project_rates.scoring import percentage_criteria
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_user,
    create_rate_project,
    link_project_to_program,
)


class WeightedMathTests(SimpleTestCase):
    def criteria(self):
        return [
            SimpleNamespace(
                pk=i,
                type="int",
                min_value=0,
                max_value=10,
                weight_percent=Decimal(str(weight)),
            )
            for i, weight in enumerate((40, 35, 25), 1)
        ]

    def test_real_percentage_example_complete_experts_and_partial_excluded(self):
        result = evaluation_totals(
            self.criteria(),
            {1: {1: "8", 2: "7", 3: "6"}, 2: {1: "10", 2: "8", 3: "8"}, 3: {1: "10"}},
            scoring_mode="weighted_percent",
        )
        self.assertEqual(result["evaluations"][1]["total"], 71.5)
        self.assertEqual(result["evaluations"][2]["total"], 88)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["score"], 79.75)
        self.assertEqual(result["maximum"], 100)
        self.assertEqual(result["contributions"], {"1": 36.0, "2": 26.25, "3": 17.5})

    def test_different_scales_minima_zero_and_maximum(self):
        criteria = self.criteria()[:2]
        criteria[0].min_value, criteria[0].max_value = 2, 6
        criteria[1].max_value, criteria[1].weight_percent = 100, Decimal("60")
        for values, expected in [
            ({1: "2", 2: "0"}, 0),
            ({1: "6", 2: "100"}, 100),
            ({1: "4", 2: "50"}, 50),
        ]:
            with self.subTest(values=values):
                self.assertEqual(
                    evaluation_totals(
                        criteria, {1: values}, scoring_mode="weighted_percent"
                    )["score"],
                    expected,
                )

    def test_non_numeric_values_still_determine_completeness_without_weight(self):
        criteria = self.criteria() + [
            SimpleNamespace(
                pk=4, type="str", min_value=None, max_value=None, weight_percent=None
            )
        ]
        result = evaluation_totals(
            criteria,
            {1: {1: "8", 2: "7", 3: "6"}, 2: {1: "8", 2: "7", 3: "6", 4: ""}},
            scoring_mode="weighted_percent",
        )
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["score"], 71.5)

    def test_invalid_configuration_cannot_calculate_a_plausible_ranking(self):
        for change in [
            dict(weight_percent=None),
            dict(weight_percent=0),
            dict(weight_percent=Decimal("0.001")),
            dict(max_value=0),
            dict(max_value=float("inf")),
            dict(weight_percent=Decimal("39.99")),
        ]:
            criteria = self.criteria()
            for key, value in change.items():
                setattr(criteria[0], key, value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                percentage_criteria(criteria)

    def test_legacy_keeps_raw_scales_even_if_unused_weights_are_present(self):
        result = evaluation_totals(self.criteria(), {1: {1: "8", 2: "7", 3: "6"}})
        self.assertEqual(result["score"], 21)
        self.assertEqual(result["maximum"], 30)


class WeightedCriteriaApiTests(TestCase):
    def setUp(self):
        self.program = create_rate_program()
        self.manager = create_rate_user()
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = f"/programs/{self.program.pk}/management/criteria/"

    def payload(self):
        snapshot = self.client.get(self.url).data
        return {
            "expected_updated_at": snapshot["updated_at"],
            "expected_revision": snapshot["revision"],
            "scoring_mode": "weighted_percent",
            "criteria": [
                dict(
                    name=f"Критерий {i}",
                    description="",
                    type="int",
                    min_value=0,
                    max_value=10,
                    weight_percent=weight,
                )
                for i, weight in enumerate((40, 35, 25), 1)
            ],
        }

    def put(self, data):
        return self.client.put(self.url, data, format="json")

    def configure(self):
        result = self.put(self.payload())
        self.assertEqual(result.status_code, 200, result.data)
        self.program.refresh_from_db()
        return result.data

    def test_roundtrip_percentages_and_explicit_mode(self):
        data = self.configure()
        self.assertEqual(data["scoring_mode"], "weighted_percent")
        self.assertEqual([c["weight_percent"] for c in data["criteria"]], [40, 35, 25])
        self.assertEqual(self.program.evaluation_scoring_mode, "weighted_percent")

    def test_invalid_numbers_ranges_sum_and_comment_weight_are_atomic(self):
        baseline = list(self.program.criterias.values())
        for field, value in [
            ("weight_percent", 0),
            ("weight_percent", -1),
            ("weight_percent", 101),
            ("weight_percent", "NaN"),
            ("weight_percent", "Infinity"),
            ("weight_percent", "40.001"),
            ("weight_percent", 39.99),
            ("max_value", 0),
        ]:
            payload = self.payload()
            payload["criteria"][0][field] = value
            with self.subTest(field=field, value=value):
                result = self.put(payload)
                self.assertEqual(result.status_code, 400, result.data)
                self.assertEqual(list(self.program.criterias.values()), baseline)
        payload = self.payload()
        payload["criteria"][0].update(type="str", min_value=None, max_value=None)
        self.assertEqual(self.put(payload).status_code, 400)

    def test_old_client_omissions_preserve_active_mode_and_weights(self):
        data = self.configure()
        for criterion in data["criteria"]:
            criterion.pop("weight_percent")
        result = self.put(
            {
                "expected_updated_at": data["updated_at"],
                "expected_revision": data["revision"],
                "criteria": data["criteria"],
            }
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["scoring_mode"], "weighted_percent")
        self.assertEqual(
            [c["weight_percent"] for c in result.data["criteria"]], [40, 35, 25]
        )

    def test_atomic_redistribution_add_remove_and_switch_back_to_legacy(self):
        data = self.configure()
        remaining = data["criteria"][:2]
        remaining[0]["weight_percent"] = 40
        remaining[1]["weight_percent"] = 60
        payload = {
            "expected_updated_at": data["updated_at"],
            "expected_revision": data["revision"],
            "criteria": remaining,
            "scoring_mode": "weighted_percent",
        }
        response = self.put(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.program.criterias.count(), 2)
        data = response.data
        payload.update(
            expected_updated_at=data["updated_at"],
            expected_revision=data["revision"],
            scoring_mode="legacy",
            criteria=[],
        )
        response = self.put(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.program.criterias.count(), 0)

    def test_model_and_individual_admin_cannot_make_active_weights_invalid(self):
        self.configure()
        criterion = self.program.criterias.order_by("pk").first()
        criterion.weight_percent = Decimal("41")
        with self.assertRaises(ValidationError):
            criterion.save()
        criterion.refresh_from_db()
        with self.assertRaises(ValidationError):
            criterion.delete()
        from project_rates.admin import CriteriaAdminForm

        form = CriteriaAdminForm(
            instance=criterion,
            data={
                "partner_program": self.program.pk,
                "name": criterion.name,
                "description": "",
                "type": "int",
                "min_value": 0,
                "max_value": 10,
                "weight_percent": "41",
            },
        )
        self.assertFalse(form.is_valid())

    def test_delete_does_not_remove_replacement_criteria_created_before_parent_lock(self):
        from unittest.mock import patch

        from partner_programs.services.management_criteria import save_criteria
        from project_rates.models import CriteriaQuerySet

        self.configure()
        original = CriteriaQuerySet.values_list
        replace = True

        def values_list(queryset, *fields, **kwargs):
            nonlocal replace
            rows = original(queryset, *fields, **kwargs)
            if replace and fields == ("pk", "partner_program_id"):
                selected = list(rows)
                replace = False
                payload = self.payload()
                payload["criteria"] = [dict(payload["criteria"][0], weight_percent=100)]
                save_criteria(self.program.pk, self.manager, payload)
                return selected
            return rows

        with patch.object(CriteriaQuerySet, "values_list", values_list):
            deleted, _ = self.program.criterias.all().delete()
        self.assertEqual(deleted, 0)
        self.assertEqual(self.program.criterias.get().weight_percent, Decimal("100"))

    def test_score_rejects_criterion_moved_before_parent_lock(self):
        from unittest.mock import patch

        from project_rates.models import CriteriaQuerySet

        target = create_rate_program()
        criterion = self.program.criterias.get(type="str")
        project = create_rate_project()
        original = CriteriaQuerySet.get
        move = True

        def get(queryset, *args, **kwargs):
            nonlocal move
            result = original(queryset, *args, **kwargs)
            if move and queryset._fields == ("partner_program_id",):
                move = False
                criterion.partner_program = target
                criterion.save()
            return result

        with patch.object(CriteriaQuerySet, "get", get):
            with self.assertRaisesMessage(ValidationError, "Критерий изменился"):
                ProjectScore.objects.create(
                    criteria=criterion, project=project, user=self.manager, value="Оценка"
                )
        criterion.refresh_from_db()
        self.assertEqual(criterion.partner_program_id, target.pk)
        self.assertFalse(ProjectScore.objects.filter(criteria=criterion).exists())

    def test_expert_response_exposes_only_active_weights_and_stale_form_cannot_save(self):
        from unittest.mock import patch
        from project_rates.tests.helpers import create_rate_expert

        snapshot = self.configure()
        expert = create_rate_expert(program=self.program)
        project = create_rate_project()
        link_project_to_program(self.program, project)
        self.client.force_authenticate(expert)
        response = self.client.get(f"/rate-project/{self.program.pk}")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            [c["weight_percent"] for c in response.data["results"][0]["criterias"]],
            [40, 35, 25],
        )
        self.client.force_authenticate(self.manager)
        body = {
            "expected_updated_at": snapshot["updated_at"],
            "expected_revision": snapshot["revision"],
            "criteria": snapshot["criteria"],
            "scoring_mode": "legacy",
        }
        after = self.put(body)
        self.assertEqual(after.status_code, 200, after.data)
        self.assertNotEqual(after.data["revision"], snapshot["revision"])
        self.client.force_authenticate(expert)
        values = [{"criterion_id": c["id"], "value": "8"} for c in snapshot["criteria"]]
        with patch("project_rates.services.send_email.delay"):
            response = self.client.post(
                f"/rate-project/rate/{project.pk}",
                {"expected_revision": snapshot["revision"], "scores": values},
                format="json",
            )
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(ProjectScore.objects.exists())
        response = self.client.get(f"/rate-project/{self.program.pk}")
        self.assertTrue(
            all(
                c["weight_percent"] is None
                for c in response.data["results"][0]["criterias"]
            )
        )

    def test_mode_and_weight_changes_change_revision_and_partial_score_freezes_them(self):
        data = self.configure()
        criterion = self.program.criterias.order_by("pk").first()
        project = create_rate_project()
        link_project_to_program(self.program, project)
        ProjectScore.objects.create(
            criteria=criterion, project=project, user=self.manager, value="8"
        )
        payload = {
            "expected_updated_at": data["updated_at"],
            "expected_revision": data["revision"],
            "criteria": data["criteria"],
            "scoring_mode": "legacy",
        }
        self.assertEqual(self.put(payload).status_code, 409)
        criterion.weight_percent = Decimal("50")
        with self.assertRaises(ValidationError):
            criterion.save()
        self.program.evaluation_scoring_mode = "legacy"
        with self.assertRaises(ValidationError):
            self.program.save(update_fields=["evaluation_scoring_mode"])

    def test_guest_foreign_manager_and_expert_cannot_set_weights(self):
        from project_rates.tests.helpers import create_rate_expert

        payload = self.payload()
        foreign_manager = create_rate_user()
        create_rate_program().managers.add(foreign_manager)
        expert = create_rate_expert(program=self.program)
        for actor, expected in [
            (None, 401),
            (create_rate_user(), 403),
            (foreign_manager, 403),
            (expert, 403),
        ]:
            self.client.force_authenticate(actor)
            self.assertEqual(self.put(payload).status_code, expected)

    def test_admin_editor_uses_the_same_atomic_weight_validation(self):
        self.manager.is_staff = self.manager.is_superuser = True
        self.manager.save()
        self.client.force_authenticate(user=None)
        self.client.force_login(self.manager)
        url = reverse(
            "admin:partner_programs_partnerprogram_evaluation_criteria",
            args=[self.program.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сохранить критерии и веса")
        from partner_programs.services.management_criteria import criteria_data

        snapshot = criteria_data(self.program)
        fields = {
            "scoring_mode": "weighted_percent",
            "expected_updated_at": snapshot["updated_at"].isoformat(),
            "expected_revision": snapshot["revision"],
            "criteria-TOTAL_FORMS": "1",
            "criteria-INITIAL_FORMS": "0",
            "criteria-MIN_NUM_FORMS": "0",
            "criteria-MAX_NUM_FORMS": "100",
            "criteria-0-name": "Качество",
            "criteria-0-type": "int",
            "criteria-0-min_value": "0",
            "criteria-0-max_value": "10",
            "criteria-0-weight_percent": "99",
        }
        self.assertEqual(self.client.post(url, fields).status_code, 400)
        self.assertEqual(self.program.criterias.count(), 1)
        fields["criteria-0-weight_percent"] = "100"
        self.assertEqual(self.client.post(url, fields).status_code, 302)
        self.program.refresh_from_db()
        self.assertEqual(self.program.evaluation_scoring_mode, "weighted_percent")
        self.assertEqual(self.program.criterias.get().weight_percent, Decimal("100"))

    def test_admin_editor_requires_model_view_and_change_permissions(self):
        from django.contrib.auth.models import Permission

        viewer = create_rate_user()
        viewer.is_staff = True
        viewer.save()
        self.client.force_authenticate(user=None)
        self.client.force_login(viewer)
        url = reverse(
            "admin:partner_programs_partnerprogram_evaluation_criteria",
            args=[self.program.pk],
        )
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        viewer.user_permissions.add(
            Permission.objects.get(codename="view_partnerprogram")
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="Сохранить критерии и веса"')
        self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_excel_exports_editable_weights_and_normalized_total_formula(self):
        data = self.configure()
        criteria = data["criteria"]
        row = dict(
            name="Команда",
            case_name="Кейс",
            completed=1,
            required=1,
            place=1,
            ready=True,
            evaluation_complete=True,
            project_id=1,
            experts=[
                dict(
                    name="Эксперт",
                    email="expert@example.test",
                    complete=True,
                    user_id=1,
                    values=[
                        dict(criterion_id=c["id"], value=value)
                        for c, value in zip(criteria, ["8", "7", "6"])
                    ],
                )
            ],
        )
        book = load_workbook(
            BytesIO(
                export_results(
                    dict(
                        scoring_mode="weighted_percent",
                        criteria=criteria,
                        groups=[dict(projects=[row])],
                    )
                )
            )
        )
        self.assertEqual(book.sheetnames, ["Рейтинг", "Оценки экспертов", "Критерии"])
        self.assertEqual(book["Критерии"]["D2"].value, 40)
        self.assertEqual(book["Критерии"].freeze_panes, "A2")
        self.assertEqual(book["Критерии"]["A1"].font.name, "Arial")
        self.assertIn("'Критерии'!D2", book["Оценки экспертов"]["I2"].value)
        self.assertIn("AVERAGEIF", book["Рейтинг"]["I2"].value)


class WeightedMigrationTests(TransactionTestCase):
    def test_existing_scores_and_old_results_keep_their_legacy_mode(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        program = create_rate_program()
        criterion = Criteria.objects.create(
            partner_program=program,
            name="Качество",
            type="int",
            min_value=0,
            max_value=10,
        )
        project = create_rate_project()
        user = create_rate_user()
        score = ProjectScore.objects.create(
            criteria=criterion, project=project, user=user, value="8"
        )
        executor = MigrationExecutor(connection)
        current = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(
                [
                    ("partner_programs", "0043_project_copy_form"),
                    ("project_rates", "0011_solution_score_value_1000"),
                ]
            )
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            old_apps = executor.loader.project_state(
                [
                    ("partner_programs", "0043_project_copy_form"),
                    ("project_rates", "0011_solution_score_value_1000"),
                ]
            ).apps
            old_program = old_apps.get_model("partner_programs", "PartnerProgram")
            fields = {
                field.attname: getattr(program, field.attname)
                for field in old_program._meta.local_fields
                if not field.primary_key
            }
            fields.update(name="Legacy writer", tag="legacy-writer-after-migration")
            created = old_program.objects.create(**fields)
            from partner_programs.models import PartnerProgram

            self.assertEqual(
                PartnerProgram.objects.get(pk=created.pk).evaluation_scoring_mode,
                "legacy",
            )
            program.refresh_from_db()
            criterion.refresh_from_db()
            score.refresh_from_db()
            self.assertEqual(program.evaluation_scoring_mode, "legacy")
            self.assertIsNone(criterion.weight_percent)
            self.assertEqual(score.value, "8")
            self.assertEqual(
                evaluation_totals([criterion], {user.pk: {criterion.pk: score.value}})[
                    "score"
                ],
                8,
            )
        finally:
            MigrationExecutor(connection).migrate(current)

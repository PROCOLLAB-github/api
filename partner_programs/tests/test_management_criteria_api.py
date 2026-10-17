from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from project_rates.models import ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


class ManagementCriteriaTests(TestCase):
    def setUp(self):
        self.program = create_rate_program()
        self.manager = create_rate_user()
        self.program.managers.add(self.manager)
        self.expert = create_rate_expert(program=self.program)
        self.project = create_rate_project()
        link_project_to_program(self.program, self.project)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = f"/programs/{self.program.pk}/management/criteria/"

    def payload(self):
        snapshot = self.client.get(self.url).data
        return dict(
            expected_updated_at=snapshot["updated_at"],
            expected_revision=snapshot["revision"],
            criteria=snapshot["criteria"],
        )

    def put(self, data):
        return self.client.put(self.url, data, format="json")

    def criterion(self, **overrides):
        return dict(
            name="Качество решения",
            description="Обоснованность",
            type="int",
            min_value=0,
            max_value=10,
            **overrides,
        )

    def test_roundtrip_all_types_and_default_comment_not_resurrected(self):
        data = self.payload()
        data["criteria"] = [
            self.criterion(),
            {**self.criterion(), "type": "bool", "min_value": None, "max_value": None},
        ]
        response = self.put(data)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["locked"])
        self.assertEqual(len(response.data["criteria"]), 2)
        self.assertNotEqual(response.data["revision"], data["expected_revision"])
        self.program.refresh_from_db()
        self.program.save()
        self.assertEqual(self.program.criterias.count(), 2)
        self.assertFalse(ProjectScore.objects.exists())

    def test_auth_scope_read_and_write(self):
        for user, code in [(None, 401), (create_rate_user(), 403)]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, code)
            self.assertEqual(self.put({}).status_code, code)

    def test_validation_and_foreign_ids_are_atomic(self):
        foreign = create_rate_criteria(create_rate_program())
        for invalid in [
            {**self.criterion(), "name": " "},
            {**self.criterion(), "max_value": -1},
            {**self.criterion(), "min_value": 0.5},
            {**self.criterion(), "max_value": None},
            {**self.criterion(), "type": "float"},
            {**self.criterion(), "id": foreign.pk},
        ]:
            data = self.payload()
            data["criteria"] = [self.criterion(), invalid]
            self.assertEqual(self.put(data).status_code, 400)
            self.assertEqual(self.program.criterias.count(), 1)

    def test_unchanged_legacy_float_and_unbounded_integer_survive(self):
        create_rate_criteria(self.program, type="float", min_value=0.1)
        create_rate_criteria(self.program)
        self.assertEqual(self.put(self.payload()).status_code, 200)

    def test_stale_configuration_rejected(self):
        data = self.payload()
        self.assertEqual(self.put(data).status_code, 200)
        self.assertEqual(self.put(data).status_code, 409)

    def test_admin_guards_and_historical_score_backfill(self):
        from importlib import import_module
        from django.apps import apps
        from django.contrib.admin.sites import AdminSite
        from django.db import connection
        from django.test import RequestFactory
        from project_rates.admin import CriteriaAdmin
        from project_rates.models import Criteria

        criterion = self.program.criterias.first()
        ProjectScore.objects.bulk_create(
            [
                ProjectScore(
                    criteria=criterion,
                    user=self.expert,
                    project=self.project,
                    value="Legacy",
                )
            ]
        )
        migration = import_module(
            "partner_programs.migrations.0021_evaluation_criteria_lock"
        )
        with connection.schema_editor() as editor:
            migration.freeze_existing(apps, editor)
        self.program.refresh_from_db()
        self.assertIsNotNone(self.program.evaluation_criteria_locked_at)
        self.manager.is_staff = True
        self.manager.is_superuser = True
        request = RequestFactory().get("/")
        request.user = self.manager
        admin = CriteriaAdmin(Criteria, AdminSite())
        self.assertFalse(admin.has_change_permission(request, criterion))
        self.assertFalse(admin.has_delete_permission(request, criterion))

    @patch("project_rates.services.send_email.delay")
    def test_zero_and_no_freeze_whole_set_and_reject_all_mutations(self, email):
        data = self.payload()
        data["criteria"] = [
            self.criterion(),
            {**self.criterion(), "type": "bool", "min_value": None, "max_value": None},
        ]
        snapshot = self.put(data).data
        self.client.force_authenticate(self.expert)
        response = self.client.post(
            f"/rate-project/rate/{self.project.pk}",
            {
                "expected_revision": snapshot["revision"],
                "scores": [
                    {
                        "criterion_id": c["id"],
                        "value": "0" if c["type"] == "int" else "False",
                    }
                    for c in snapshot["criteria"]
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.manager)
        self.assertTrue(self.client.get(self.url).data["locked"])
        self.assertEqual(self.put(self.payload()).data["code"], "criteria_locked")
        criterion = self.program.criterias.first()
        criterion.name = "Changed"
        with self.assertRaises(ValidationError):
            criterion.save()
        with self.assertRaises(ValidationError):
            self.program.criterias.all().delete()
        with self.assertRaises(ValidationError):
            create_rate_criteria(self.program)
        ProjectScore.objects.all().delete()
        self.assertTrue(self.client.get(self.url).data["locked"])

    @patch("project_rates.services.send_email.delay")
    def test_stale_expert_form_and_missing_revision_do_not_save_or_lock(self, email):
        old = self.payload()
        snapshot = self.put(old).data
        self.client.force_authenticate(self.expert)
        url = f"/rate-project/rate/{self.project.pk}"
        scores = [{"criterion_id": snapshot["criteria"][0]["id"], "value": "OK"}]
        # A no-op configuration save still requires a current form revision, not an old cached client.
        self.assertEqual(self.client.post(url, scores, format="json").status_code, 409)
        self.assertEqual(
            self.client.post(
                url, {"expected_revision": "old", "scores": scores}, format="json"
            ).status_code,
            409,
        )
        self.assertFalse(ProjectScore.objects.exists())
        self.program.refresh_from_db()
        self.assertIsNone(self.program.evaluation_criteria_locked_at)

    @patch("project_rates.services.send_email.delay")
    def test_integer_validation_rejects_fractions_nan_and_out_of_range(self, email):
        criterion = create_rate_criteria(self.program, min_value=-2, max_value=10)
        self.client.force_authenticate(self.expert)
        for value in ["1.5", "NaN", "Infinity", "-3", "11"]:
            response = self.client.post(
                f"/rate-project/rate/{self.project.pk}",
                [{"criterion_id": criterion.pk, "value": value}],
                format="json",
            )
            self.assertEqual(response.status_code, 400, (value, response.data))
        self.assertFalse(ProjectScore.objects.exists())


class CriteriaRaceTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    @patch("project_rates.services.send_email.delay")
    def test_first_score_and_manager_save_are_serialized(self, email):
        from partner_programs.services.management_criteria import (
            criteria_data,
            save_criteria,
        )
        from project_rates.services import submit_project_scores
        from project_rates.criteria_policy import CriteriaConflict

        program = create_rate_program()
        manager = create_rate_user()
        program.managers.add(manager)
        expert = create_rate_expert(program=program)
        project = create_rate_project()
        link_project_to_program(program, project)
        criterion = create_rate_criteria(program, min_value=0, max_value=10)
        snapshot = criteria_data(program)
        payload = {
            "expected_updated_at": snapshot["updated_at"],
            "expected_revision": snapshot["revision"],
            "criteria": snapshot["criteria"],
        }
        payload["criteria"][-1]["max_value"] = 5
        barrier = Barrier(2)

        def run(action):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                if action == "manager":
                    save_criteria(program.pk, manager, payload)
                else:
                    submit_project_scores(
                        user=expert,
                        project_id=project.pk,
                        data={
                            "expected_revision": snapshot["revision"],
                            "scores": [{"criterion_id": criterion.pk, "value": "8"}],
                        },
                    )
                return "ok"
            except CriteriaConflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, ["manager", "expert"]))
        self.assertCountEqual(results, ["ok", "conflict"])
        criterion.refresh_from_db()
        if ProjectScore.objects.exists():
            self.assertEqual(criterion.max_value, 10)
        else:
            self.assertEqual(criterion.max_value, 5)

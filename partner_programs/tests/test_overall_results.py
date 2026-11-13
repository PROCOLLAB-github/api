from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APIClient

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    ProgramQuizOutcome,
)
from partner_programs.services.quiz_outcomes import (
    QuizOutcomeConflict,
    record_quiz_outcome,
)
from project_rates.models import Criteria, ProjectScore
from project_rates.tests.helpers import (
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


def weighted_program(**kwargs):
    program = create_rate_program(is_competitive=True, required_evaluators=2, **kwargs)
    program.criterias.all().delete()
    criterion = Criteria.objects.create(
        partner_program=program,
        name="Оценка кейса",
        type="int",
        min_value=0,
        max_value=10,
        weight_percent=100,
    )
    program.evaluation_scoring_mode = "weighted_percent"
    program.save()
    return program, criterion


def team(program, *, name="Команда", case_field=None, case_name="Право", submitted=True):
    project = create_rate_project(name=name)
    project.name = name
    project.save()
    program.users.add(project.leader, through_defaults={"partner_program_data": {}})
    link = link_project_to_program(program, project)
    if case_field:
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=case_field, value_text=case_name
        )
    PartnerProgramProject.objects.filter(pk=link.pk).update(submitted=submitted)
    return project, link


class OverallResultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.program, cls.criterion = weighted_program()
        cls.manager = create_rate_user()
        cls.program.managers.add(cls.manager)
        cls.experts = [create_rate_expert(program=cls.program) for _ in range(2)]
        cls.case_field = PartnerProgramField.objects.create(
            partner_program=cls.program,
            name="case",
            label="Кейс",
            field_type="select",
            options="Право|Общество",
            is_required=True,
            show_filter=True,
        )
        cls.projects, cls.links = {}, {}
        for name, points, quiz, submitted, case in (
            ("Максимум", [10, 10], 100, True, "Право"),
            ("Альфа", [8, 8], 90, True, "Право"),
            ("Бета", [9, 9], 80, True, "Общество"),
            ("Гамма", [7, 7], 70, True, "Право"),
            ("Ноль", [0, 0], 0, True, "Право"),
            ("Кейс готов", [10, 10], None, True, "Право"),
            ("Квиз готов", [8], 100, True, "Право"),
            ("Не сдан", [8, 8], 50, False, "Право"),
            ("Ничего", [], None, True, "Право"),
        ):
            project, link = team(
                cls.program,
                name=name,
                case_field=cls.case_field,
                case_name=case,
                submitted=submitted,
            )
            cls.projects[name], cls.links[name] = project, link
            for expert, score in zip(cls.experts, points):
                ProjectScore.objects.create(
                    criteria=cls.criterion, project=project, user=expert, value=str(score)
                )
            if quiz is not None:
                record_quiz_outcome(
                    cls.program.pk, project.pk, f"quiz:{project.pk}", quiz
                )

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.manager)

    def url(self, export=False, program=None):
        return reverse(
            "partner_programs:management-overall-results" + ("-export" if export else ""),
            kwargs={"pk": (program or self.program).pk},
        )

    def snapshot(self, **query):
        response = self.api.get(self.url(), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def rows(self, **query):
        return {row["name"]: row for row in self.snapshot(**query)["projects"]}

    def test_sum_200_zero_and_competition_places_across_cases(self):
        data = self.snapshot()
        self.assertEqual(
            (data["case_maximum"], data["quiz_maximum"], data["maximum"]), (100, 100, 200)
        )
        self.assertEqual((data["total_count"], data["ready_count"]), (9, 5))
        rows = self.rows()
        for name, score, place in (
            ("Максимум", 200, 1),
            ("Альфа", 170, 2),
            ("Бета", 170, 2),
            ("Гамма", 140, 4),
            ("Ноль", 0, 5),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    (rows[name]["score"], rows[name]["place"], rows[name]["ready"]),
                    (score, place, True),
                )
        self.assertEqual((rows["Ноль"]["case_score"], rows["Ноль"]["quiz_score"]), (0, 0))

    def test_pending_stages_are_not_zero_or_ranked(self):
        rows = self.rows()
        for name, status in (
            ("Кейс готов", "pending_quiz"),
            ("Квиз готов", "pending_case"),
            ("Не сдан", "pending_case"),
            ("Ничего", "pending_both"),
        ):
            self.assertEqual(rows[name]["status"], status)
            self.assertIsNone(rows[name]["score"])
            self.assertIsNone(rows[name]["place"])
        self.assertEqual(rows["Кейс готов"]["case_score"], 100)
        self.assertEqual(rows["Квиз готов"]["case_score"], 80)
        self.assertFalse(rows["Квиз готов"]["case_complete"])
        self.assertEqual(rows["Не сдан"]["case_status"], "not_submitted")
        self.assertIsNone(rows["Не сдан"]["case_score"])

    def test_official_case_score_is_reused_without_different_rounding(self):
        case = self.api.get(f"/programs/{self.program.pk}/management/results/").data
        expected = {r["id"]: r for g in case["groups"] for r in g["projects"]}
        for row in self.snapshot()["projects"]:
            if row["submitted"]:
                self.assertEqual(row["case_score"], expected[row["id"]]["score"])
                self.assertEqual(row["case_complete"], expected[row["id"]]["ready"])

    def test_filter_and_search_keep_global_places(self):
        rows = self.rows(search="Гамма")
        self.assertEqual(set(rows), {"Гамма"})
        self.assertEqual(rows["Гамма"]["place"], 4)
        rows = self.rows(case_scope="selected", case_name="Общество")
        self.assertEqual(set(rows), {"Бета"})
        self.assertEqual(rows["Бета"]["place"], 2)
        self.assertEqual(len(self.rows(status="pending")), 4)
        self.assertEqual(len(self.rows(status="complete")), 5)

    def test_sort_ascending_keeps_pending_last_and_places_unchanged(self):
        rows = self.snapshot(order="asc")["projects"]
        self.assertEqual(rows[0]["name"], "Ноль")
        self.assertEqual(rows[0]["place"], 5)
        self.assertEqual([r["ready"] for r in rows], [True] * 5 + [False] * 4)

    def test_get_scope_all_cannot_bypass_current_filters(self):
        self.assertEqual(set(self.rows(scope="all", search="Гамма")), {"Гамма"})

    def test_invalid_filters_are_rejected_including_full_export(self):
        for export in (False, True):
            for query in (
                {"status": "invalid"},
                {"order": "invalid"},
                {"case_scope": "selected", "case_name": "Чужой кейс", "scope": "all"},
            ):
                with self.subTest(export=export, query=query):
                    self.assertEqual(
                        self.api.get(self.url(export), query).status_code, 400
                    )

    def test_only_own_manager_and_staff_can_read_and_export(self):
        member = self.projects["Альфа"].leader
        foreign = create_rate_user()
        other = create_rate_program()
        other.managers.add(foreign)
        for actor in (member, self.experts[0], foreign):
            self.api.force_authenticate(actor)
            for export in (False, True):
                self.assertEqual(self.api.get(self.url(export)).status_code, 403)
        self.api.force_authenticate(None)
        self.assertIn(self.api.get(self.url()).status_code, (401, 403))
        self.manager.is_staff = True
        self.manager.save()
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.get(self.url()).status_code, 200)

    def test_unknown_program_and_public_score_writes_are_rejected(self):
        self.assertEqual(
            self.api.get("/programs/999999/management/overall-results/").status_code, 404
        )
        before = ProgramQuizOutcome.objects.count()
        self.assertEqual(self.api.post(self.url(), {"quiz_score": 100}).status_code, 405)
        self.assertEqual(self.api.put(self.url(), {"quiz_score": 100}).status_code, 405)
        self.assertEqual(ProgramQuizOutcome.objects.count(), before)

    def test_no_expert_personal_data_or_attempt_ids_in_response(self):
        data = self.api.get(self.url())
        self.assertIn("no-store", data["Cache-Control"])
        body = data.content.decode()
        for key in ('"experts"', '"email"', '"source_attempt_id"'):
            self.assertNotIn(key, body)

    def test_raw_case_points_are_added_without_normalizing_or_summing_experts(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            evaluation_scoring_mode="legacy"
        )
        data = self.snapshot()
        self.assertTrue(data["case_scoring_configured"])
        self.assertEqual((data["case_maximum"], data["maximum"]), (10, 110))
        rows = self.rows()
        self.assertEqual((rows["Альфа"]["case_score"], rows["Альфа"]["score"]), (8, 98))
        self.assertEqual((rows["Ноль"]["score"], rows["Ноль"]["ready"]), (0, True))
        self.assertEqual(rows["Квиз готов"]["status"], "pending_case")
        old = self.api.get(f"/programs/{self.program.pk}/management/results/")
        self.assertEqual(old.status_code, 200)
        self.assertEqual(old.data["maximum"], 10)

    def test_raw_three_criteria_keep_24_out_of_30_before_adding_quiz(self):
        program = create_rate_program(is_competitive=True, required_evaluators=2)
        program.criterias.all().delete()
        program.managers.add(self.manager)
        criteria = [
            Criteria.objects.create(
                partner_program=program, name=name, type="int", min_value=0, max_value=10
            )
            for name in ("Решение", "Реализуемость", "Презентация")
        ]
        project, _ = team(program, name="Три критерия")
        for _ in range(2):
            expert = create_rate_expert(program=program)
            for criterion in criteria:
                ProjectScore.objects.create(
                    criteria=criterion, project=project, user=expert, value="8"
                )
        record_quiz_outcome(program.pk, project.pk, "raw-three-criteria-quiz", 90)
        data = self.api.get(self.url(program=program)).data
        row = data["projects"][0]
        self.assertEqual(
            (row["case_score"], row["quiz_score"], row["score"]), (24, 90, 114)
        )
        self.assertEqual((data["case_maximum"], data["maximum"]), (30, 130))

    def test_raw_case_can_exceed_100_and_share_values_with_admin_and_excel(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            evaluation_scoring_mode="legacy"
        )
        Criteria.objects.filter(pk=self.criterion.pk).update(max_value=200)
        ProjectScore.objects.filter(project=self.projects["Альфа"]).update(value="170")
        row = self.rows()["Альфа"]
        self.assertEqual((row["case_score"], row["score"]), (170, 260))
        self.assertEqual(self.snapshot()["maximum"], 300)
        sheet = load_workbook(BytesIO(self.api.get(self.url(True)).content)).active
        exported = next(r for r in sheet.iter_rows(min_row=2) if r[1].value == "Альфа")
        self.assertEqual(exported[3].value, 170)
        self.assertEqual(
            [sheet.cell(1, c).value for c in (4, 5, 6)],
            ["Баллы за кейс", "Баллы за квиз", "Итог"],
        )
        self.manager.is_staff = self.manager.is_superuser = True
        self.manager.save()
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse(
                "admin:partner_programs_partnerprogram_overall_results",
                args=[self.program.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context_data["snapshot"]["projects"], self.snapshot()["projects"]
        )
        self.assertNotContains(response, "из 200")
        self.assertContains(response, "Баллы за кейс")

    def test_unbounded_legacy_scale_has_no_invented_maximum(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            evaluation_scoring_mode="legacy"
        )
        Criteria.objects.filter(pk=self.criterion.pk).update(max_value=None)
        data = self.snapshot()
        self.assertIsNone(data["case_maximum"])
        self.assertIsNone(data["maximum"])
        self.assertEqual(self.rows()["Альфа"]["score"], 98)

    def test_comment_only_program_keeps_teams_and_quiz_without_a_case_score(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            evaluation_scoring_mode="legacy"
        )
        Criteria.objects.filter(pk=self.criterion.pk).update(
            type="str", min_value=None, max_value=None, weight_percent=None
        )
        data = self.snapshot()
        self.assertFalse(data["case_scoring_configured"])
        self.assertEqual(len(data["projects"]), 9)
        self.assertEqual(data["ready_count"], 0)
        self.assertTrue(
            all(
                r["status"] == "configuration_required" and r["score"] is None
                for r in data["projects"]
            )
        )
        self.assertEqual(self.rows()["Альфа"]["quiz_score"], 90)

    def test_empty_program_has_explicit_empty_result(self):
        program, _ = weighted_program()
        program.managers.add(self.manager)
        response = self.api.get(self.url(program=program))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["projects"], [])
        self.assertEqual(response.data["maximum"], 200)

    def test_unrelated_program_quiz_results_do_not_enter_current_rating(self):
        other, _ = weighted_program()
        other.users.add(
            self.projects["Не сдан"].leader, through_defaults={"partner_program_data": {}}
        )
        link_project_to_program(other, self.projects["Не сдан"])
        record_quiz_outcome(
            other.pk, self.projects["Не сдан"].pk, "other-program-attempt", 100
        )
        self.assertEqual(self.rows()["Не сдан"]["quiz_score"], 50)

    def test_decimal_quiz_result_is_added_to_official_case_score(self):
        project, _ = team(self.program, name="Сотые балла", submitted=True)
        for expert, score in zip(self.experts, (3, 4)):
            ProjectScore.objects.create(
                criteria=self.criterion, project=project, user=expert, value=str(score)
            )
        record_quiz_outcome(self.program.pk, project.pk, "decimal-attempt", "33.33")
        row = self.rows()["Сотые балла"]
        self.assertEqual(
            (row["case_score"], row["quiz_score"], row["score"]), (35, 33.33, 68.33)
        )

    def test_unsupported_program_contours_do_not_mix_models(self):
        for changes in ({"solution_storage_mode": "solution"}, {"is_competitive": False}):
            with self.subTest(changes=changes):
                original = {key: getattr(self.program, key) for key in changes}
                PartnerProgram.objects.filter(pk=self.program.pk).update(**changes)
                self.assertEqual(self.api.get(self.url()).status_code, 409)
                PartnerProgram.objects.filter(pk=self.program.pk).update(**original)

    def test_xlsx_has_same_places_values_formulas_and_plain_arial_10(self):
        response = self.api.get(self.url(export=True))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        book = load_workbook(BytesIO(response.content), data_only=False)
        self.assertEqual(book.sheetnames, ["Общий рейтинг"])
        sheet = book.active
        self.assertEqual(sheet.freeze_panes, "A2")
        expected = self.rows()
        for index in range(2, sheet.max_row + 1):
            row = expected[sheet.cell(index, 2).value]
            self.assertEqual(sheet.cell(index, 1).value, row["place"])
            self.assertEqual(sheet.cell(index, 4).value, row["case_score"])
            self.assertEqual(sheet.cell(index, 5).value, row["quiz_score"])
            self.assertEqual(
                sheet.cell(index, 6).value,
                f"=ROUND(D{index}+E{index},2)" if row["ready"] else None,
            )
            if row["ready"]:
                self.assertEqual(
                    Decimal(str(sheet.cell(index, 4).value))
                    + Decimal(str(sheet.cell(index, 5).value)),
                    Decimal(str(row["score"])),
                )
        for cells in sheet:
            for cell in cells:
                self.assertEqual((cell.font.name, cell.font.sz), ("Arial", 10))
                self.assertEqual(cell.font.bold, cell.row == 1)
                self.assertIsNone(cell.fill.patternType)
                self.assertIsNone(cell.comment)

    def test_export_scope_full_and_formula_injection_safety(self):
        project = self.projects["Альфа"]
        project.name = '=HYPERLINK("https://example.test","name")'
        project.save()
        response = self.api.get(self.url(True), {"search": "Ноль", "scope": "all"})
        sheet = load_workbook(BytesIO(response.content)).active
        self.assertEqual(sheet.max_row, 10)
        cell = next(
            row[1] for row in sheet.iter_rows(min_row=2) if row[1].value == project.name
        )
        self.assertEqual(cell.data_type, "s")
        selected = load_workbook(
            BytesIO(self.api.get(self.url(True), {"search": "Ноль"}).content)
        ).active
        self.assertEqual(selected.max_row, 2)

    def test_queries_do_not_grow_per_team(self):
        self.snapshot()
        with CaptureQueriesContext(connection) as before:
            self.snapshot()
        for i in range(12):
            team(self.program, name=f"Дополнительная {i}", submitted=False)
        with CaptureQueriesContext(connection) as after:
            self.snapshot()
        self.assertLessEqual(len(after), len(before) + 1)

    def test_admin_uses_same_results_and_refuses_manual_quiz_edit(self):
        staff = create_rate_user()
        staff.is_staff = True
        staff.save()
        staff.user_permissions.add(
            Permission.objects.get(codename="view_partnerprogram"),
            Permission.objects.get(codename="view_programquizoutcome"),
        )
        self.client.force_login(staff)
        url = reverse(
            "admin:partner_programs_partnerprogram_overall_results",
            args=[self.program.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context_data["snapshot"]["projects"], self.snapshot()["projects"]
        )
        self.assertContains(response, "Баллы за кейс")
        self.assertContains(response, "0,00")
        self.assertContains(response, "1 из 2 оценок")
        selected = self.client.get(url, {"search": "Гамма", "scope": "all"})
        self.assertEqual(
            [row["name"] for row in selected.context_data["snapshot"]["projects"]],
            ["Гамма"],
        )
        self.assertEqual(self.client.post(url, {"quiz_score": 100}).status_code, 405)
        export = reverse(
            "admin:partner_programs_partnerprogram_overall_results_export",
            args=[self.program.pk],
        )
        self.assertEqual(self.client.get(export).status_code, 200)
        outcome = ProgramQuizOutcome.objects.first()
        self.assertEqual(
            self.client.get(
                reverse(
                    "admin:partner_programs_programquizoutcome_change", args=[outcome.pk]
                )
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "admin:partner_programs_programquizoutcome_change", args=[outcome.pk]
                ),
                {"score": 100},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("admin:partner_programs_programquizoutcome_add")
            ).status_code,
            403,
        )

    def test_admin_requires_model_permissions(self):
        staff = create_rate_user()
        staff.is_staff = True
        staff.save()
        self.client.force_login(staff)
        url = reverse(
            "admin:partner_programs_partnerprogram_overall_results",
            args=[self.program.pk],
        )
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_filter_errors_are_plain_text_not_executable_html(self):
        staff = create_rate_user()
        staff.is_staff = staff.is_superuser = True
        staff.save()
        self.client.force_login(staff)
        for name in ("overall_results", "overall_results_export"):
            url = reverse(
                "admin:partner_programs_partnerprogram_" + name, args=[self.program.pk]
            )
            response = self.client.get(url, {"status": "<script>alert(1)</script>"})
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response["Content-Type"].startswith("text/plain"))


class QuizOutcomeTests(TestCase):
    def setUp(self):
        self.program, _ = weighted_program()
        self.project, self.link = team(self.program, submitted=False)

    def record(self, score="80.25", attempt="stable-attempt"):
        return record_quiz_outcome(self.program.pk, self.project.pk, attempt, score)

    def test_idempotent_record_does_not_change_timestamp(self):
        first = self.record()
        second = self.record(score=Decimal("80.25"))
        self.assertEqual((first.pk, first.recorded_at), (second.pk, second.recorded_at))
        self.assertEqual(ProgramQuizOutcome.objects.count(), 1)

    def test_conflicting_attempt_or_score_cannot_replace_result(self):
        first = self.record()
        for score, attempt in (("81", "stable-attempt"), ("80.25", "another-attempt")):
            with self.subTest(score=score, attempt=attempt), self.assertRaises(
                QuizOutcomeConflict
            ):
                self.record(score, attempt)
        first.refresh_from_db()
        self.assertEqual(first.score, Decimal("80.25"))

    def test_missing_registration_and_foreign_program_are_rejected(self):
        other, _ = weighted_program()
        from django.http import Http404

        with self.assertRaises(Http404):
            record_quiz_outcome(other.pk, self.project.pk, "foreign-attempt", 100)
        self.assertFalse(ProgramQuizOutcome.objects.exists())

    def test_same_attempt_cannot_be_used_by_another_team(self):
        self.record()
        project, _ = team(self.program, submitted=False)
        with self.assertRaises(QuizOutcomeConflict):
            record_quiz_outcome(self.program.pk, project.pk, "stable-attempt", 80.25)

    def test_rejoining_preserves_same_team_result_and_one_attempt(self):
        first = self.record()
        self.link.delete()
        link_project_to_program(self.program, self.project)
        self.assertEqual(self.record().pk, first.pk)
        with self.assertRaises(QuizOutcomeConflict):
            self.record(attempt="retry-after-rejoin")

    def test_invalid_scores_are_rejected_without_creating_records(self):
        from rest_framework.exceptions import ValidationError

        for value in (
            None,
            True,
            "NaN",
            "Infinity",
            "-Infinity",
            "-0.01",
            "100.01",
            "1.001",
            "bad",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.record(score=value)
        self.assertFalse(ProgramQuizOutcome.objects.exists())

    def test_empty_or_overlong_attempt_ids_are_rejected(self):
        from rest_framework.exceptions import ValidationError

        for value in (None, "", " ", " x", "x ", "x" * 129):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.record(attempt=value)

    def test_unsupported_program_cannot_accept_quiz_outcome(self):
        from rest_framework.exceptions import ValidationError

        for change in ({"solution_storage_mode": "solution"}, {"is_competitive": False}):
            original = {key: getattr(self.program, key) for key in change}
            PartnerProgram.objects.filter(pk=self.program.pk).update(**change)
            with self.assertRaises(ValidationError):
                self.record()
            PartnerProgram.objects.filter(pk=self.program.pk).update(**original)
        self.assertFalse(ProgramQuizOutcome.objects.exists())

    def test_model_and_queryset_refuse_changes_to_completed_outcome(self):
        outcome = self.record()
        outcome.score = Decimal("90")
        with self.assertRaises(ModelValidationError):
            outcome.save()
        with self.assertRaises(ModelValidationError):
            ProgramQuizOutcome.objects.filter(pk=outcome.pk).update(score=90)
        with self.assertRaises(ModelValidationError):
            ProgramQuizOutcome.objects.bulk_update([outcome], ["score"])

    def test_database_range_constraint_is_enforced(self):
        outcome = self.record()
        for value in ("101", "-0.01", "NaN"):
            with self.subTest(value=value), self.assertRaises(
                IntegrityError
            ), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE partner_programs_programquizoutcome SET score=%s WHERE id=%s",
                        [value, outcome.pk],
                    )

    def test_database_unique_team_constraint_is_enforced(self):
        self.record()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO partner_programs_programquizoutcome "
                    "(program_id,project_id,source_attempt_id,score,recorded_at) "
                    "VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP)",
                    [self.program.pk, self.project.pk, "different-attempt", 50],
                )

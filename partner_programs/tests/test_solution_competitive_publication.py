import copy
import json
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram, PartnerProgramField
from partner_programs.services import (
    solution_archive_actions,
    solution_case_actions,
    solution_member_actions,
)
from partner_programs.services.publishing import publish_finished_program_solutions
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionAdministrativeChange,
    SolutionInvitation,
)
from partner_programs.tests.helpers import create_program_member, create_user
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_publication import PublicationFixture
from project_rates.solution_models import SolutionExpertAssignment, SolutionScore
from project_rates.tests.helpers import create_rate_criteria, create_rate_expert
from projects.models import Project


FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class CompetitivePublicationFixture(PublicationFixture):
    def setUp(self):
        self.seed_publication()
        self.program.is_competitive = True
        self.program.save(update_fields=["is_competitive"])

    def submit_ready(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200, response.data)
        self.solution.refresh_from_db()
        self.now = timezone.now()

    def archive(self):
        data = dict(ids=[self.solution.pk])
        preview = solution_archive_actions.preview(self.program.pk, self.manager, data)
        return solution_archive_actions.apply(
            self.program.pk,
            self.manager,
            dict(**data, preview_token=preview["preview_token"]),
        )


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class CompetitivePublicationTests(CompetitivePublicationFixture, TestCase):
    def test_submitted_only_is_published_without_altering_submission_or_projects(self):
        draft = self.other_solution(name="Несданная работа")
        self.submit_ready()
        before = ProgramSolution.all_objects.filter(pk=self.solution.pk).values().get()
        projects = list(Project.objects.order_by("pk").values())
        self.assertEqual(self.publish(), 1)
        after = ProgramSolution.all_objects.filter(pk=self.solution.pk).values().get()
        self.assertEqual(after, dict(before, published_at=self.now))
        draft.refresh_from_db()
        self.assertIsNone(draft.published_at)
        self.assertEqual(self.read()["count"], 1)
        self.assertEqual(self.read(self.solution)["application"]["name"], before["name"])
        self.assertEqual(list(Project.objects.order_by("pk").values()), projects)

    def test_published_materials_search_and_roster_use_only_the_applied_snapshot(self):
        member, pending = create_user(), create_user()
        for user in (member, pending):
            create_program_member(
                self.program, user=user, data={"secret": "private-form"}
            )
        ProgramSolutionMember.objects.create(
            solution=self.solution, user=member, role="Дизайнер"
        )
        SolutionInvitation.objects.create(
            solution=self.solution,
            recipient=pending,
            motivational_letter="private-invite",
        )
        file = self.upload()
        self.assertEqual(
            self.save_answers(
                [dict(field_id=self.fields["file"]["id"], value=dict(url=file.pk))],
                name="Сданное название",
            ).status_code,
            200,
        )
        self.submit_ready()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        ProgramSolution.objects.filter(pk=self.solution.pk).update(name="Живое имя")
        ProgramSolutionAnswer.objects.filter(
            solution=self.solution, field_id=self.fields["number"]["id"]
        ).update(value=999)
        PartnerProgramField.objects.filter(pk=self.fields["number"]["id"]).update(
            label="Новая живая подпись"
        )
        added = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="after_submission",
            field_type="textarea",
            label="Новое обязательное поле",
            is_required=True,
            purpose="other",
            position=99,
        )
        self.assertEqual(self.publish(), 1)
        data = self.read(self.solution)
        self.assertEqual(data["application"]["name"], "Сданное название")
        self.assertEqual(self.read(query="?search=Сданное")["count"], 1)
        self.assertEqual(self.read(query="?search=Живое")["count"], 0)
        answers = {row["field_id"]: row["value"] for row in data["answers"]}
        self.assertEqual(answers[self.fields["number"]["id"]], 0)
        self.assertIs(answers[self.fields["checkbox"]["id"]], False)
        self.assertEqual(answers[self.fields["file"]["id"]], {"url": file.pk})
        self.assertEqual(
            data["fields"][2]["label"], snapshot["form"]["fields"][2]["label"]
        )
        self.assertNotIn(added.pk, [field["id"] for field in data["fields"]])
        self.assertCountEqual(
            [row["user"]["id"] for row in data["team"]["members"]],
            [self.captain.pk, member.pk],
        )
        encoded = json.dumps(data)
        for secret in (
            member.email,
            pending.email,
            "private-form",
            "private-invite",
            "submission_snapshot",
            "permissions",
        ):
            self.assertNotIn(secret, encoded)

    def test_draft_with_marker_is_hidden_for_every_role_and_not_counted(self):
        ProgramSolution.objects.filter(pk=self.solution.pk).update(published_at=self.now)
        for actor in (None, self.captain, self.manager, create_user()):
            page = call(actor, "get", self.public_url)
            self.assertEqual(page.status_code, 200, page.data)
            self.assertEqual(page.data["count"], 0)
            detail = call(actor, "get", self.public_url + f"{self.solution.pk}/")
            self.assertEqual(detail.status_code, 404, detail.data)
            self.assert_schema("Error", detail.data)

    def test_pagination_counts_submitted_only_and_foreign_program_cannot_read_it(self):
        self.submit_ready()
        draft, second = self.other_solution(), self.other_solution(name="Второе решение")
        root = f"/programs/{self.program.pk}/solutions/{second.pk}/"
        current = call(second.captain, "get", root).data
        saved = call(
            second.captain,
            "patch",
            root,
            dict(
                expected_version=current["version"],
                expected_form_revision=current["form"]["revision"],
                answers=list(
                    self.solution.answers.order_by("pk").values("field_id", "value")
                ),
            ),
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        submitted = call(
            second.captain,
            "post",
            root + "submit/",
            dict(
                expected_version=saved.data["version"],
                expected_form_revision=saved.data["form"]["revision"],
            ),
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        ProgramSolution.objects.filter(pk=draft.pk).update(published_at=self.now)
        self.assertEqual(self.publish(), 2)
        page = self.read(query="?limit=1")
        self.assertEqual(page["count"], 2)
        self.assertEqual(
            page["results"][0]["application"]["solution_id"], self.solution.pk
        )
        following = APIClient().get(page["next"])
        self.assertEqual(following.status_code, 200, following.data)
        self.assertEqual(
            following.data["results"][0]["application"]["solution_id"], second.pk
        )
        self.assertIsNone(following.data["next"])
        self.assertIsNotNone(following.data["previous"])
        foreign = self.other_solution(program=self.other_program())
        for actor in (None, self.manager, self.captain):
            response = call(
                actor,
                "get",
                f"/programs/{foreign.program_id}/published-solutions/{self.solution.pk}/",
            )
            self.assertEqual(response.status_code, 404, response.data)

    def other_program(self):
        from partner_programs.tests.helpers import create_partner_program

        return create_partner_program(
            solution_storage_mode="solution", is_competitive=True
        )

    def test_flag_date_boundary_repeat_and_disabled_creation_keep_first_marker(self):
        self.submit_ready()
        for changes in (
            dict(publish_projects_after_finish=False),
            dict(datetime_finished=self.now + timezone.timedelta(seconds=1)),
        ):
            PartnerProgram.objects.filter(pk=self.program.pk).update(**changes)
            self.assertEqual(publish_finished_program_solutions(now=self.now), 0)
            self.solution.refresh_from_db()
            self.assertIsNone(self.solution.published_at)
            PartnerProgram.objects.filter(pk=self.program.pk).update(
                publish_projects_after_finish=True, datetime_finished=self.now
            )
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            solution_creation_enabled=False
        )
        self.assertEqual(self.publish(), 1)
        later = self.now + timezone.timedelta(days=1)
        self.assertEqual(publish_finished_program_solutions(now=later), 0)
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            publish_projects_after_finish=False, datetime_finished=later
        )
        self.assertEqual(self.read()["count"], 1)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, self.now)

    def test_get_and_first_submission_do_not_publish_without_job(self):
        self.assertEqual(self.read()["count"], 0)
        self.submit_ready()
        self.assertEqual(self.read()["count"], 0)
        self.assertEqual(
            APIClient().get(self.public_url + f"{self.solution.pk}/").status_code, 404
        )
        self.solution.refresh_from_db()
        self.assertIsNone(self.solution.published_at)
        self.assertEqual(self.publish(), 1)
        self.assertEqual(self.read()["count"], 1)

    def test_public_reads_never_query_or_expose_private_scores_and_assignments(self):
        self.submit_ready()
        criterion = create_rate_criteria(self.program, type="str")
        expert = create_rate_expert(program=self.program)
        SolutionExpertAssignment.objects.create(
            solution=self.solution, expert=expert.expert, partner_program=self.program
        )
        SolutionScore.objects.create(
            solution=self.solution,
            criteria=criterion,
            user=expert,
            value="private-score",
        )
        self.assertEqual(self.publish(), 1)
        with CaptureQueriesContext(connection) as queries:
            data = self.read(self.solution)
        self.assertFalse(any("project_rates_" in row["sql"] for row in queries))
        encoded = json.dumps(data)
        for secret in (
            "private-score",
            "criteria",
            "assignments",
            "scores",
            expert.email,
        ):
            self.assertNotIn(secret, encoded)
        self.assertEqual(APIClient().get(self.url).status_code, 401)

    def test_confirmed_case_member_revisions_are_public_without_private_history(self):
        member = create_user()
        create_program_member(self.program, user=member)
        ProgramSolutionMember.objects.create(
            solution=self.solution, user=member, role="Разработчик"
        )
        PartnerProgramField.objects.filter(pk=self.fields["select"]["id"]).update(
            solution_options=["Задача 1", "Задача 2"], options="Задача 1|Задача 2"
        )
        self.submit_ready()
        original = copy.deepcopy(self.solution.submission_snapshot)
        self.assertEqual(self.publish(), 1)
        case = {"case_name": "Задача 2"}
        preview = solution_case_actions.preview(
            self.program.pk, self.solution.pk, self.manager, case
        )
        solution_case_actions.apply(
            self.program.pk,
            self.solution.pk,
            self.manager,
            dict(**case, preview_token=preview["preview_token"]),
        )
        remove = {"user_id": member.pk}
        preview = solution_member_actions.preview(
            self.program.pk, self.solution.pk, self.manager, remove
        )
        solution_member_actions.apply(
            self.program.pk,
            self.solution.pk,
            self.manager,
            dict(**remove, preview_token=preview["preview_token"]),
        )
        data = self.read(self.solution)
        answers = {row["field_id"]: row["value"] for row in data["answers"]}
        self.assertEqual(answers[self.fields["select"]["id"]], "Задача 2")
        self.assertEqual(data["team"]["accepted_count"], 1)
        events = SolutionAdministrativeChange.objects.filter(
            solution=self.solution
        ).order_by("pk")
        self.assertEqual(events.count(), 2)
        self.assertEqual(events.first().before_snapshot, original)
        self.assertNotIn("before_snapshot", json.dumps(data))
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, self.now)

    def test_archive_before_or_after_publication_excludes_work_and_retains_snapshot(self):
        self.submit_ready()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        self.assertEqual(self.publish(), 1)
        self.archive()
        self.assertEqual(self.read()["count"], 0)
        self.assertEqual(
            APIClient().get(self.public_url + f"{self.solution.pk}/").status_code, 404
        )
        self.assertEqual(self.publish(), 0)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot, snapshot)
        self.assertEqual(self.solution.published_at, self.now)


@override_settings(PASSWORD_HASHERS=FAST_HASHERS)
class CompetitivePublicationLockTests(CompetitivePublicationFixture, TransactionTestCase):
    def waiting_worker(self, pool, command):
        backend = Queue()

        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend.put(cursor.fetchone()[0])
                return command()
            finally:
                close_old_connections()

        future = pool.submit(run)
        pid, deadline = backend.get(timeout=10), monotonic() + 10
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT cardinality(pg_blocking_pids(%s))", [pid])
                if cursor.fetchone()[0]:
                    self.assertFalse(future.done())
                    return future
            sleep(0.02)
        self.fail("Publisher/archive worker не дождался program lock.")

    def test_waiting_publisher_rechecks_archived_work_after_program_lock(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.submit_ready()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                PartnerProgram.objects.select_for_update().get(pk=self.program.pk)
                future = self.waiting_worker(pool, self.publish)
                self.archive()
            self.assertEqual(future.result(timeout=10), 0)
        self.solution.refresh_from_db()
        self.assertIsNone(self.solution.published_at)
        self.assertIsNotNone(self.solution.archived_at)
        self.assertEqual(self.read()["count"], 0)

    def test_waiting_archive_preserves_marker_and_removes_public_visibility(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.submit_ready()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                PartnerProgram.objects.select_for_update().get(pk=self.program.pk)
                self.assertEqual(self.publish(), 1)
                future = self.waiting_worker(pool, self.archive)
            self.assertEqual(future.result(timeout=10)["changed_count"], 1)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, self.now)
        self.assertEqual(self.read()["count"], 0)

    def test_waiting_repeat_publisher_preserves_first_publication_time(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.submit_ready()
        first = self.now
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                PartnerProgram.objects.select_for_update().get(pk=self.program.pk)
                self.assertEqual(self.publish(), 1)
                self.now += timezone.timedelta(seconds=1)
                future = self.waiting_worker(pool, self.publish)
            self.assertEqual(future.result(timeout=10), 0)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, first)

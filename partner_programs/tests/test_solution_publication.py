import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import skipUnless

from django.contrib import admin
from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from files.models import UserFile
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramUserProfile,
)
from partner_programs.services.publishing import (
    publish_finished_program_projects,
    publish_finished_program_solutions,
    publish_solution_program,
)
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_models import (
    ProgramSolution,
    ProgramSolutionAnswer,
    ProgramSolutionMember,
    SolutionInvitation,
)
from partner_programs.tasks import publish_finished_program_solutions_task
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.tests.test_solution_forms import call
from partner_programs.tests.test_solution_submission import SubmissionFixture
from projects.models import Project


class PublicationFixture(SubmissionFixture):
    def seed_publication(self):
        self.ready()
        self.now = timezone.now()
        self.program.is_competitive = False
        self.program.publish_projects_after_finish = True
        self.program.datetime_finished = self.now - timezone.timedelta(days=1)
        self.program.save(
            update_fields=[
                "is_competitive",
                "publish_projects_after_finish",
                "datetime_finished",
            ]
        )
        self.public_url = f"/programs/{self.program.pk}/published-solutions/"

    def publish(self):
        return publish_solution_program(self.program.pk, now=self.now)

    def other_solution(self, program=None, name="Еще одно решение"):
        program = program or self.program
        captain = create_user()
        create_program_member(program, user=captain)
        solution = ProgramSolution.objects.create(
            program=program, captain=captain, name=name
        )
        ProgramSolutionMember.objects.create(solution=solution, user=captain)
        return solution

    def assert_schema(self, name, data):
        from jsonschema import Draft202012Validator, FormatChecker

        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(
            {"components": spec["components"], "$ref": f"#/components/schemas/{name}"},
            format_checker=FormatChecker(),
        ).validate(data)

    def read(self, solution=None, query=""):
        suffix = f"{solution.pk}/" if solution else ""
        response = APIClient().get(self.public_url + suffix + query)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assert_schema(
            "PublishedSolution" if solution else "PublishedSolutionPage", response.data
        )
        return response.data


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionPublicationTests(PublicationFixture, TestCase):
    def setUp(self):
        self.seed_publication()

    def test_publisher_marks_saved_noncompetitive_without_submit_or_other_changes(self):
        self.solution.refresh_from_db()
        before = self.solution.version, self.solution.updated_at, self.solution.status
        files, projects = UserFile.objects.count(), Project.objects.count()
        self.assertEqual(self.publish(), 1)
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, self.now)
        self.assertEqual(
            (self.solution.version, self.solution.updated_at, self.solution.status),
            before,
        )
        self.assertIsNone(self.solution.submitted_at)
        self.assertIsNone(self.solution.submission_snapshot)
        self.assertEqual(UserFile.objects.count(), files)
        self.assertEqual(Project.objects.count(), projects)

    def test_no_flag_future_or_competitive_is_not_published(self):
        original_end = self.program.datetime_finished
        for changes in [
            dict(publish_projects_after_finish=False),
            dict(datetime_finished=self.now + timezone.timedelta(seconds=1)),
            dict(is_competitive=True),
        ]:
            PartnerProgram.objects.filter(pk=self.program.pk).update(**changes)
            self.assertEqual(publish_finished_program_solutions(now=self.now), 0)
            self.solution.refresh_from_db()
            self.assertIsNone(self.solution.published_at)
            PartnerProgram.objects.filter(pk=self.program.pk).update(
                publish_projects_after_finish=True,
                datetime_finished=original_end,
                is_competitive=False,
            )
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            datetime_finished=self.now
        )
        self.assertEqual(self.publish(), 1)

    def test_repeated_and_late_publication_preserve_marker_after_flag_disabled(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            publish_projects_after_finish=False
        )
        self.assertEqual(self.publish(), 0)
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            publish_projects_after_finish=True
        )
        self.assertEqual(self.publish(), 1)
        later = self.now + timezone.timedelta(days=2)
        self.assertEqual(publish_finished_program_solutions(now=later), 0)
        PartnerProgram.objects.filter(pk=self.program.pk).update(
            publish_projects_after_finish=False,
            datetime_finished=later,
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, self.now)
        self.assertEqual(self.read()["count"], 1)
        self.read(self.solution)

    def test_partial_and_empty_materials_are_publishable_saved_work(self):
        ProgramSolutionAnswer.objects.filter(solution=self.solution).delete()
        self.assertEqual(self.publish(), 1)
        data = self.read(self.solution)
        self.assertEqual(data["answers"], [])
        self.assertTrue(any(field["required"] for field in data["fields"]))
        self.assertEqual(data["team"]["accepted_count"], 1)

    def test_get_is_read_only_and_does_not_publish_an_eligible_work(self):
        self.assertEqual(self.read()["count"], 0)
        response = APIClient().get(self.public_url + f"{self.solution.pk}/")
        self.assertEqual(response.status_code, 404)
        self.solution.refresh_from_db()
        self.assertIsNone(self.solution.published_at)

    def test_public_materials_keep_zero_false_files_and_only_accepted_people(self):
        member, pending = create_user(), create_user()
        for user in [member, pending]:
            create_program_member(
                self.program, user=user, data={"private_phone": "registration-secret"}
            )
        ProgramSolutionMember.objects.create(
            solution=self.solution, user=member, role="Разработчик"
        )
        SolutionInvitation.objects.create(
            solution=self.solution,
            recipient=pending,
            motivational_letter="invitation-secret",
        )
        file = self.upload()
        self.assertEqual(
            self.save_answers(
                [dict(field_id=self.fields["file"]["id"], value=dict(url=file.pk))]
            ).status_code,
            200,
        )
        self.publish()
        data = self.read(self.solution)
        answers = {row["field_id"]: row["value"] for row in data["answers"]}
        self.assertEqual(answers[self.fields["number"]["id"]], 0)
        self.assertIs(answers[self.fields["checkbox"]["id"]], False)
        self.assertEqual(answers[self.fields["file"]["id"]], {"url": file.pk})
        self.assertCountEqual(
            [row["user"]["id"] for row in data["team"]["members"]],
            [self.captain.pk, member.pk],
        )
        self.assertEqual(sum(row["is_captain"] for row in data["team"]["members"]), 1)
        self.assertEqual(
            set(data), {"application", "published_at", "fields", "answers", "team"}
        )
        encoded = json.dumps(data, ensure_ascii=False)
        for secret in [
            self.captain.email,
            member.email,
            "registration-secret",
            "invitation-secret",
            "1990-01-01",
        ]:
            self.assertNotIn(secret, encoded)
        self.assertEqual(
            set(data["team"]["members"][0]["user"]),
            {"id", "first_name", "last_name", "avatar_url"},
        )

    def test_allowed_edit_after_publication_is_visible_and_stale_save_cannot_revoke(self):
        stale = ProgramSolution.objects.get(pk=self.solution.pk)
        version = stale.version
        self.publish()
        stale.name = "Обычная модельная правка"
        stale.save()
        stale.refresh_from_db()
        self.assertEqual(stale.published_at, self.now)
        self.assertEqual(stale.version, version)
        self.assertEqual(self.read(self.solution)["application"]["name"], stale.name)
        self.assertEqual(self.save_answers(name="Обновленное решение").status_code, 200)
        self.assertEqual(
            self.read(self.solution)["application"]["name"], "Обновленное решение"
        )

    def test_public_answers_do_not_expose_private_objects_or_file_metadata(self):
        file = self.upload()
        self.assertEqual(
            self.save_answers(
                [
                    dict(field_id=self.fields["file"]["id"], value=dict(url=file.pk)),
                    dict(
                        field_id=self.fields["url"]["id"],
                        value="https://example.org/demo",
                    ),
                ]
            ).status_code,
            200,
        )
        for kind in ["textarea", "number"]:
            ProgramSolutionAnswer.objects.filter(
                solution=self.solution,
                field_id=self.fields[kind]["id"],
            ).update(value={"private_email": "private-value@example.org"})
        ProgramSolutionAnswer.objects.filter(
            solution=self.solution,
            field_id=self.fields["file"]["id"],
        ).update(value={"url": file.pk, "owner_email": "private-value@example.org"})
        ProgramSolutionAnswer.objects.filter(
            solution=self.solution,
            field_id=self.fields["url"]["id"],
        ).update(value="javascript:alert(1)")
        self.publish()
        data = self.read(self.solution)
        answers = {row["field_id"]: row["value"] for row in data["answers"]}
        self.assertNotIn(self.fields["textarea"]["id"], answers)
        self.assertNotIn(self.fields["number"]["id"], answers)
        self.assertNotIn(self.fields["url"]["id"], answers)
        self.assertEqual(answers[self.fields["file"]["id"]], {"url": file.pk})
        self.assertNotIn("private-value", json.dumps(data))

    def test_owner_api_model_and_admin_cannot_assign_publication_timestamp(self):
        response = self.save_answers(published_at=self.now.isoformat())
        self.assertEqual(response.status_code, 400)
        self.solution.published_at = self.now
        self.solution.save(update_fields=["published_at"])
        self.solution.refresh_from_db()
        self.assertIsNone(self.solution.published_at)
        self.assertFalse(ProgramSolution._meta.get_field("published_at").editable)
        self.assertIn(
            "published_at",
            admin.site._registry[ProgramSolution].get_readonly_fields(
                None, self.solution
            ),
        )

    def test_list_count_order_search_pagination_and_safe_query(self):
        second = self.other_solution(name="Другой прототип")
        self.publish()
        data = self.read(query="?limit=1")
        self.assertEqual(data["count"], 2)
        self.assertEqual(
            data["results"][0]["application"]["solution_id"], self.solution.pk
        )
        self.assertIn("offset=1", data["next"])
        page = APIClient().get(data["next"])
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data["results"][0]["application"]["solution_id"], second.pk)
        self.assertIsNotNone(page.data["previous"])
        self.assertEqual(self.read(query="?search=Другой")["count"], 1)
        for query in [
            "?limit=0",
            "?limit=101",
            "?offset=-1",
            "?unknown=1",
            "?submission=all",
        ]:
            response = APIClient().get(self.public_url + query)
            self.assertEqual(response.status_code, 400, response.data)
            self.assert_schema("Error", response.data)

    def test_unpublished_foreign_unknown_unsafe_are_hidden_for_every_role(self):
        unpublished = self.other_solution()
        self.publish()
        later = self.other_solution()
        for actor in [None, self.captain, self.manager, create_user()]:
            for identifier in [later.pk, MAX_ID, MAX_ID + 1, 0]:
                response = call(actor, "get", self.public_url + f"{identifier}/")
                self.assertEqual(response.status_code, 404)
                self.assert_schema("Error", response.data)
        other = create_partner_program(
            solution_storage_mode="solution", is_competitive=False
        )
        foreign_url = self.public_url.replace(f"/{self.program.pk}/", f"/{other.pk}/")
        self.assertEqual(
            APIClient().get(foreign_url + f"{unpublished.pk}/").status_code, 404
        )

    def test_legacy_and_competitive_are_not_exposed_by_partial_publication_block(self):
        self.publish()
        for changes in [
            dict(is_competitive=True),
            dict(solution_storage_mode="legacy_project"),
        ]:
            PartnerProgram.objects.filter(pk=self.program.pk).update(**changes)
            self.assertEqual(APIClient().get(self.public_url).status_code, 404)
            self.assertEqual(
                APIClient().get(self.public_url + f"{self.solution.pk}/").status_code, 404
            )
            PartnerProgram.objects.filter(pk=self.program.pk).update(
                is_competitive=False, solution_storage_mode="solution"
            )

    def test_private_read_and_public_write_permissions_are_unchanged(self):
        self.publish()
        self.assertEqual(APIClient().get(self.url).status_code, 401)
        self.assertEqual(call(create_user(), "get", self.url).status_code, 404)
        self.assertEqual(
            APIClient().post(self.public_url, {}, format="json").status_code, 405
        )
        self.assertEqual(
            APIClient()
            .post(self.public_url + f"{self.solution.pk}/", {}, format="json")
            .status_code,
            405,
        )
        response = APIClient().get(self.public_url + f"{self.solution.pk}/?unknown=1")
        self.assertEqual(response.status_code, 400)

    def test_snapshot_is_allowlisted_and_does_not_read_later_live_values(self):
        self.program.is_competitive = True
        self.program.save(update_fields=["is_competitive"])
        self.assertEqual(self.submit().status_code, 200)
        self.solution.refresh_from_db()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        name = snapshot["name"]
        snapshot["members"][0]["user"]["email"] = "snapshot-private@example.com"
        snapshot["form"]["fields"][0]["internal"] = "snapshot-private"
        ProgramSolution.objects.filter(pk=self.solution.pk).update(
            name="Другое текущее имя", submission_snapshot=snapshot
        )
        ProgramSolutionAnswer.objects.filter(
            solution=self.solution, field_id=self.fields["number"]["id"]
        ).update(value=999)
        PartnerProgramField.objects.filter(pk=self.fields["number"]["id"]).update(
            label="Новая подпись"
        )
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        self.publish()
        data = self.read(self.solution)
        self.assertEqual(data["application"]["name"], name)
        self.assertNotIn("snapshot-private", json.dumps(data))
        self.assertNotIn("Новая подпись", json.dumps(data, ensure_ascii=False))
        self.assertEqual(
            {row["field_id"]: row["value"] for row in data["answers"]}[
                self.fields["number"]["id"]
            ],
            0,
        )
        self.assertEqual(self.read(query="?search=" + name)["count"], 1)

    def test_legacy_publisher_does_not_publish_projects_linked_to_solution_program(self):
        project = create_project()
        profile_project = create_project(leader=self.captain)
        create_program_project(self.program, project=project)
        # Историческая анкета могла сохранять Project до включения нового режима.
        PartnerProgramUserProfile.objects.filter(
            partner_program=self.program,
            user=self.captain,
        ).update(project=profile_project)
        legacy = create_partner_program(
            publish_projects_after_finish=True,
            datetime_finished=self.now - timezone.timedelta(days=1),
        )
        legacy_link, legacy_profile = create_project(), create_project()
        create_program_project(legacy, project=legacy_link)
        create_program_member(legacy, user=legacy_profile.leader, project=legacy_profile)
        self.assertEqual(publish_finished_program_projects(now=self.now), 2)
        for private in [project, profile_project]:
            private.refresh_from_db()
            self.assertFalse(private.is_public)
        for public in [legacy_link, legacy_profile]:
            public.refresh_from_db()
            self.assertTrue(public.is_public)
        self.assertEqual(self.publish(), 1)
        self.assertEqual(Project.objects.count(), 4)

    def test_daily_task_publishes_once_without_project_task_result_change(self):
        self.assertEqual(publish_finished_program_solutions_task.run(), 1)
        self.assertEqual(publish_finished_program_solutions_task.run(), 0)
        from procollab.celery import app

        self.assertEqual(
            app.conf.beat_schedule["publish_finished_program_solutions"]["schedule"],
            app.conf.beat_schedule["publish_finished_program_projects"]["schedule"],
        )

    def test_list_and_detail_query_count_does_not_grow_per_solution(self):
        self.publish()
        with CaptureQueriesContext(connection) as initial:
            self.read()
        for index in range(8):
            self.other_solution(name=f"Решение {index}")
        self.publish()
        with CaptureQueriesContext(connection) as expanded:
            result = self.read()
        self.assertEqual(len(result["results"]), 9)
        self.assertEqual(len(initial), len(expanded))
        self.assertLessEqual(len(expanded), 6)
        with CaptureQueriesContext(connection) as detail_queries:
            self.read(self.solution)
        self.assertLessEqual(len(detail_queries), 6)
        self.assertFalse(any("project_rates_" in row["sql"] for row in detail_queries))


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL locks")
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionPublicationConcurrencyTests(PublicationFixture, TransactionTestCase):
    def test_two_publishers_keep_one_marker_and_one_count(self):
        self.seed_publication()
        barrier = Barrier(2)

        def publish():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return publish_solution_program(self.program.pk, now=self.now)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: publish(), range(2)))
        self.assertCountEqual(results, [0, 1])
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.published_at, self.now)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SolutionPublicationMigrationTests(TransactionTestCase):
    def test_existing_solution_remains_private_after_migration(self):
        before = [("partner_programs", "0032_alter_programsolution_options")]
        after = [("partner_programs", "0033_solution_publication")]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(before)
            old_apps = executor.loader.project_state(before).apps
            program, captain = (
                create_partner_program(solution_storage_mode="solution"),
                create_user(),
            )
            solution = old_apps.get_model(
                "partner_programs", "ProgramSolution"
            ).objects.create(program_id=program.pk, captain_id=captain.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            current = ProgramSolution.objects.get(pk=solution.pk)
            self.assertIsNone(current.published_at)
            self.assertEqual(current.status, "draft")
        finally:
            MigrationExecutor(connection).migrate(after)

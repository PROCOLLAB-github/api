"""Возврат в черновик: права, сохранность данных, повтор и Django admin."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth.models import Permission
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram, ProgramRegistration
from partner_programs.services.program_launch import readiness, publish_program
from partner_programs.solution_models import ProgramSolution, ProgramSolutionMember
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_user,
)
from project_rates.models import Criteria, ProjectScore


class ProgramUnpublishTests(TestCase):
    def setUp(self):
        self.manager = create_user(is_active=True)
        self.program = create_partner_program()
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = f"/programs/{self.program.pk}/management/unpublish/"
        self.body = {"expected_updated_at": self.program.datetime_updated.isoformat()}

    def post(self, **changes):
        return self.client.post(self.url, {**self.body, **changes}, format="json")

    def test_transition_preserves_records_and_all_other_program_fields(self):
        member = create_program_member(self.program, data={"answer": "Сохранить"})
        link = create_program_project(self.program, submitted=True)
        criterion = Criteria.objects.create(
            partner_program=self.program, name="Критерий", type="int"
        )
        score = ProjectScore.objects.create(
            criteria=criterion, user=self.manager, project=link.project, value="5"
        )
        solution = ProgramSolution.objects.create(
            program=self.program,
            captain=member.user,
        )
        membership = ProgramSolutionMember.objects.create(
            solution=solution, user=member.user
        )
        solution.status = "submitted"
        solution.submitted_at = timezone.now()
        solution.submission_snapshot = {"name": "Решение"}
        solution.save()
        material = self.program.materials.create(
            title="Правила", url="https://example.com/rules"
        )
        config = ProgramRegistration.objects.create(
            program=self.program,
            draft={"mode": "native", "fields": []},
            published={"mode": "native", "fields": []},
            published_version=3,
            revision=4,
            published_at=timezone.now(),
        )
        records = [member, link, score, solution, membership, material, config]
        before = [
            (obj, type(obj).objects.filter(pk=obj.pk).values().get()) for obj in records
        ]
        program_before = PartnerProgram.objects.filter(pk=self.program.pk).values().get()

        response = self.post()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["draft"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.program.refresh_from_db()
        self.assertGreater(
            self.program.datetime_updated, program_before["datetime_updated"]
        )
        program_after = PartnerProgram.objects.filter(pk=self.program.pk).values().get()
        for key in ("draft", "datetime_updated"):
            program_before.pop(key)
            program_after.pop(key)
        self.assertEqual(program_before, program_after)
        for obj, snapshot in before:
            self.assertEqual(type(obj).objects.filter(pk=obj.pk).values().get(), snapshot)

    def test_draft_is_hidden_from_public_and_participants_but_manager_keeps_access(self):
        participant = create_program_member(self.program).user
        self.assertEqual(self.post().status_code, 200)
        for user in (None, participant, create_user()):
            self.client.force_authenticate(user)
            for suffix in (
                "",
                "registration/",
                "published-solutions/",
                "published-projects/",
            ):
                self.assertEqual(
                    self.client.get(f"/programs/{self.program.pk}/{suffix}").status_code,
                    404,
                    suffix,
                )
            catalog = self.client.get("/programs/").data
            self.assertNotIn(self.program.pk, [row["id"] for row in catalog["results"]])
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.client.get(f"/programs/{self.program.pk}/management/").status_code, 200
        )
        self.assertTrue(
            self.client.get(f"/programs/{self.program.pk}/management/launch/").data[
                "program"
            ]["draft"]
        )

    def test_permissions_are_object_scoped_without_creation_permission(self):
        other_manager = create_user()
        create_partner_program().managers.add(other_manager)
        for user, expected in ((None, 401), (other_manager, 403)):
            self.client.force_authenticate(user)
            self.assertEqual(self.post().status_code, expected)
            self.program.refresh_from_db()
            self.assertFalse(self.program.draft)
        self.client.force_authenticate(self.manager)
        self.assertFalse(self.manager.has_perm("partner_programs.add_partnerprogram"))
        self.assertEqual(self.post().status_code, 200)
        self.client.force_authenticate(other_manager)
        self.assertEqual(self.post().status_code, 404)

    def test_staff_can_return_program_to_draft(self):
        self.client.force_authenticate(create_user(is_staff=True))
        self.assertEqual(self.post().status_code, 200)

    def test_missing_program_and_invalid_payloads_do_not_write(self):
        missing = self.client.post(
            "/programs/2147483647/management/unpublish/", self.body, format="json"
        )
        self.assertEqual(missing.status_code, 404)
        for body in ({}, {"expected_updated_at": "bad"}, {**self.body, "draft": True}):
            self.assertEqual(
                self.client.post(self.url, body, format="json").status_code, 400
            )
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)

    def test_stale_version_rejects_transition_and_retry_is_idempotent(self):
        self.program.name = "Изменено другим организатором"
        self.program.save(update_fields=["name", "datetime_updated"])
        response = self.post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "stale_settings")
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)
        self.assertEqual(
            self.post(
                expected_updated_at=self.program.datetime_updated.isoformat()
            ).status_code,
            200,
        )
        self.program.refresh_from_db()
        version = self.program.datetime_updated
        self.assertEqual(self.post().status_code, 200)
        self.program.refresh_from_db()
        self.assertEqual(self.program.datetime_updated, version)

    def test_republication_preserves_answers_and_rejects_old_publish_revision(self):
        schema = {"mode": "native", "fields": []}
        config = ProgramRegistration.objects.create(
            program=self.program,
            draft=schema,
            published=schema,
            published_version=1,
        )
        member = create_program_member(self.program, data={"historical": "Ответ"})
        previous_revision = readiness(self.program.pk, self.manager)["revision"]
        self.assertEqual(self.post().status_code, 200)
        response = self.client.post(
            f"/programs/{self.program.pk}/management/publish/",
            {"revision": previous_revision},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        state = readiness(self.program.pk, self.manager)
        self.assertTrue(state["can_publish"])
        publish_program(self.program.pk, self.manager, state["revision"])
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)
        member.refresh_from_db()
        self.assertEqual(member.partner_program_data, {"historical": "Ответ"})
        config.refresh_from_db()
        self.assertEqual(config.published_version, 2)
        self.assertEqual(self.post().status_code, 409)


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class ProgramUnpublishAdminTests(TestCase):
    def setUp(self):
        self.admin = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.admin)
        self.program = create_partner_program()
        self.url = reverse(
            "admin:partner_programs_partnerprogram_unpublish", args=[self.program.pk]
        )
        self.change_url = reverse(
            "admin:partner_programs_partnerprogram_change", args=[self.program.pk]
        )

    def test_admin_get_is_confirmation_only_and_post_uses_same_transition(self):
        self.assertContains(self.client.get(self.change_url), self.url)
        page = self.client.get(self.url)
        self.assertContains(page, "Участники, заявки, решения и оценки сохранятся")
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)
        response = self.client.post(
            self.url, {"expected_updated_at": self.program.datetime_updated.isoformat()}
        )
        self.assertRedirects(response, self.change_url)
        self.program.refresh_from_db()
        self.assertTrue(self.program.draft)
        self.assertNotContains(self.client.get(self.change_url), self.url)

    def test_admin_requires_change_permission_and_csrf(self):
        staff = create_user(is_staff=True, is_active=True)
        self.program.managers.add(staff)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(
            client.post(
                self.url,
                {"expected_updated_at": self.program.datetime_updated.isoformat()},
            ).status_code,
            403,
        )
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)
        staff.user_permissions.add(
            Permission.objects.get(codename="change_partnerprogram")
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_admin_stale_confirmation_keeps_program_published(self):
        version = self.program.datetime_updated.isoformat()
        self.program.name = "Новое название"
        self.program.save()
        response = self.client.post(self.url, {"expected_updated_at": version})
        self.assertContains(
            response, "Программа изменена другим организатором", status_code=409
        )
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)


class ProgramUnpublishConcurrencyTests(TransactionTestCase):
    def test_simultaneous_retries_write_one_transition(self):
        manager = create_user(is_active=True)
        program = create_partner_program()
        program.managers.add(manager)
        body = {"expected_updated_at": program.datetime_updated.isoformat()}
        barrier = Barrier(2)

        def post(_):
            try:
                client = APIClient()
                client.force_authenticate(type(manager).objects.get(pk=manager.pk))
                barrier.wait(timeout=10)
                result = client.post(
                    f"/programs/{program.pk}/management/unpublish/", body, format="json"
                )
                return result.status_code, result.data["updated_at"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(post, range(2)))
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(len({version for _, version in results}), 1)
        program.refresh_from_db()
        self.assertTrue(program.draft)

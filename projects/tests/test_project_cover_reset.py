"""Права legacy-проекта и сохранность файлов при возврате стандартной обложки."""

from unittest.mock import Mock, patch

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from files.models import UserFile
from invites.models import Invite
from project_rates.tests.helpers import create_rate_expert
from projects.cover_reset import cleanup_previous_cover, reset_project_cover
from projects.models import DefaultProjectCover, Project
from projects.serializers import ProjectDetailSerializer
from projects.views import ProjectDetail, ProjectResetCover

from .helpers import (
    add_program_member,
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
    link_project_to_program,
)


class ProjectCoverResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = create_project(is_public=False)
        cls.leader = cls.project.leader
        cls.other = create_user()
        cls.custom = UserFile.objects.create(
            link="https://files.example.com/custom.png", user=cls.leader
        )
        cls.default = UserFile.objects.create(
            link="https://files.example.com/default.png", user=cls.other
        )
        DefaultProjectCover.objects.create(image=cls.default)
        cls.project.cover_image_address = cls.custom.link
        cls.project.save(update_fields=["cover_image_address"])

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.leader)
        self.url = f"/projects/{self.project.pk}/reset-cover/"
        self.detail_url = f"/projects/{self.project.pk}/"
        self.cdn_patch = patch("projects.cover_reset.cdn")
        self.cdn = self.cdn_patch.start()
        self.addCleanup(self.cdn_patch.stop)
        self.cdn.delete.return_value = Mock(status_code=204)

    def reset(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, {}, format="json")

    def test_custom_reset_commits_before_owned_file_cleanup(self):
        def delete_after_switch(url):
            self.project.refresh_from_db()
            self.assertEqual(self.project.cover_image_address, self.default.link)
            return Mock(status_code=204)

        self.cdn.delete.side_effect = delete_after_switch
        response = self.reset()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data,
            {"cover_image_address": self.default.link, "is_default_cover": True},
        )
        self.cdn.delete.assert_called_once_with(self.custom.link)
        self.assertFalse(UserFile.objects.filter(pk=self.custom.pk).exists())
        self.assertTrue(UserFile.objects.filter(pk=self.default.pk).exists())
        self.assertTrue(self.client.get(self.detail_url).data["is_default_cover"])

    def test_default_reset_is_idempotent_even_when_file_owned_by_caller(self):
        UserFile.objects.filter(pk=self.default.pk).update(user=self.leader)
        Project.objects.filter(pk=self.project.pk).update(
            cover_image_address=self.default.link
        )
        for _ in range(2):
            response = self.reset()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["cover_image_address"], self.default.link)
        self.cdn.delete.assert_not_called()
        self.assertTrue(DefaultProjectCover.objects.filter(image=self.default).exists())
        self.assertTrue(UserFile.objects.filter(pk=self.default.pk).exists())

    def test_no_available_default_returns_controlled_conflict_without_changes(self):
        DefaultProjectCover.objects.all().delete()
        DefaultProjectCover.objects.create(image=None)
        response = self.reset()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "default_cover_unavailable")
        self.project.refresh_from_db()
        self.assertEqual(self.project.cover_image_address, self.custom.link)
        self.cdn.delete.assert_not_called()
        self.assertTrue(UserFile.objects.filter(pk=self.custom.pk).exists())

    def test_unavailable_rows_do_not_hide_an_available_default(self):
        DefaultProjectCover.objects.create(image=None)
        self.assertEqual(self.reset().status_code, 200)

    def test_foreign_file_is_preserved(self):
        UserFile.objects.filter(pk=self.custom.pk).update(user=self.other)
        self.assertEqual(self.reset().status_code, 200)
        self.cdn.delete.assert_not_called()
        self.assertTrue(UserFile.objects.filter(pk=self.custom.pk).exists())

    def test_missing_old_file_does_not_prevent_reset(self):
        self.custom.delete()
        self.assertEqual(self.reset().status_code, 200)
        self.cdn.delete.assert_not_called()

    def test_file_referenced_by_another_project_is_preserved(self):
        other_project = create_project(leader=self.leader)
        Project.objects.filter(pk=other_project.pk).update(
            cover_image_address=self.custom.link
        )
        self.assertEqual(self.reset().status_code, 200)
        self.cdn.delete.assert_not_called()
        self.assertTrue(UserFile.objects.filter(pk=self.custom.pk).exists())

    def test_cleanup_network_failure_keeps_success_and_does_not_log_exception(self):
        self.cdn.delete.side_effect = RuntimeError("private-url-or-token")
        with self.assertLogs("projects.cover_reset", level="WARNING") as logs:
            response = self.reset()
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.cover_image_address, self.default.link)
        self.assertTrue(UserFile.objects.filter(pk=self.custom.pk).exists())
        self.assertNotIn("private-url-or-token", " ".join(logs.output))

    def test_cleanup_http_failure_keeps_success_and_file_record(self):
        self.cdn.delete.return_value.raise_for_status.side_effect = RuntimeError()
        with self.assertLogs("projects.cover_reset", level="WARNING"):
            self.assertEqual(self.reset().status_code, 200)
        self.assertTrue(UserFile.objects.filter(pk=self.custom.pk).exists())
        self.project.refresh_from_db()
        self.assertEqual(self.project.cover_image_address, self.default.link)

    def test_cleanup_404_is_idempotent(self):
        self.cdn.delete.return_value = Mock(status_code=404)
        self.assertEqual(self.reset().status_code, 200)
        self.assertFalse(UserFile.objects.filter(pk=self.custom.pk).exists())

    def test_cleanup_rechecks_system_file_status(self):
        DefaultProjectCover.objects.create(image=self.custom)
        cleanup_previous_cover(self.custom.link, self.leader.pk)
        self.cdn.delete.assert_not_called()
        self.assertTrue(UserFile.objects.filter(pk=self.custom.pk).exists())

    def test_rollback_never_runs_cleanup(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    reset_project_cover(self.project, self.leader.pk)
                    raise RuntimeError("rollback")
        self.assertEqual(callbacks, [])
        self.cdn.delete.assert_not_called()
        self.project.refresh_from_db()
        self.assertEqual(self.project.cover_image_address, self.custom.link)

    def test_permissions_are_identical_to_project_update(self):
        self.assertIs(
            ProjectResetCover.permission_classes, ProjectDetail.permission_classes
        )
        collaborator = create_collaborator(self.project).user
        invited = create_user()
        Invite.objects.create(project=self.project, user=invited)
        program = create_partner_program()
        link_project_to_program(self.project, program)
        manager = create_user()
        program.managers.add(manager)
        expert = create_rate_expert(program=program)
        for draft in (True, False):
            for user in (self.leader, collaborator, invited, manager, expert, self.other):
                with self.subTest(draft=draft, user=user.pk):
                    Project.objects.filter(pk=self.project.pk).update(draft=draft)
                    self.client.force_authenticate(user)
                    expected = (
                        200
                        if user == self.leader
                        or (draft and user in (collaborator, invited))
                        else 403
                    )
                    update = self.client.put(
                        self.detail_url,
                        {"name": "Проверка прав", "draft": draft},
                        format="json",
                    )
                    self.assertEqual(update.status_code, expected, update.data)
                    reset = self.reset()
                    self.assertEqual(reset.status_code, expected, reset.data)

    def test_program_timing_restriction_remains_in_force(self):
        program = create_partner_program(finished=True)
        add_program_member(program, self.leader, project=self.project)
        self.assertEqual(self.reset().status_code, 403)
        self.project.refresh_from_db()
        self.assertEqual(self.project.cover_image_address, self.custom.link)

    def test_anonymous_and_missing_project(self):
        self.client.force_authenticate(None)
        self.assertIn(self.reset().status_code, (401, 403))
        self.client.force_authenticate(self.leader)
        self.assertEqual(
            self.client.post("/projects/99999999/reset-cover/").status_code, 404
        )

    def test_global_delete_foreign_file_still_forbidden(self):
        response = self.client.delete(f"/files/?link={self.default.link}")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserFile.objects.filter(pk=self.default.pk).exists())

    def test_detail_flag_tracks_actual_url_and_is_read_only(self):
        self.assertFalse(self.client.get(self.detail_url).data["is_default_cover"])
        response = self.client.put(
            self.detail_url,
            {
                "draft": True,
                "cover_image_address": self.default.link,
                "is_default_cover": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_default_cover"])
        Project.objects.filter(pk=self.project.pk).update(cover_image_address=None)
        self.assertFalse(self.client.get(self.detail_url).data["is_default_cover"])

    def test_detail_many_adds_one_default_query_independent_of_list_size(self):
        projects = [self.project] + [create_project() for _ in range(4)]
        for count in (1, 5):
            with self.subTest(count=count), CaptureQueriesContext(connection) as queries:
                data = ProjectDetailSerializer(projects[:count], many=True).data
            self.assertEqual(len(data), count)
            default_queries = [
                q for q in queries if "projects_defaultprojectcover" in q["sql"]
            ]
            self.assertEqual(len(default_queries), 1)

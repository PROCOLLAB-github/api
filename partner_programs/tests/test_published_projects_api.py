from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramProject
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
    create_program_member,
)


class PublishedProjectsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.program = create_partner_program(
            publish_projects_after_finish=True,
            datetime_finished=timezone.now() - timezone.timedelta(days=1),
        )
        self.user = create_user()
        self.public = create_project(leader=self.user, is_public=True, name="Public work")
        self.private = create_project(leader=self.user, is_public=False)
        self.draft = create_project(leader=self.user, is_public=True, draft=True)
        for project in (self.public, self.private, self.draft):
            PartnerProgramProject.objects.create(
                partner_program=self.program, project=project
            )
        self.url = f"/programs/{self.program.pk}/published-projects/"

    def read(self, path=None, **kwargs):
        return self.client.get(path or self.url, secure=True, **kwargs)

    def test_anonymous_reader_publishes_due_non_drafts_without_waiting_for_task(self):
        response = self.read()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.data["results"]],
            [self.public.pk, self.private.pk],
        )
        self.assertNotIn("program_data", response.data["results"][0])
        self.assertNotIn("scores", response.data["results"][0])
        self.private.refresh_from_db()
        self.assertTrue(self.private.is_public)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_publication_happens_at_exact_deadline_and_on_late_flag_enable(self):
        deadline = timezone.now()
        self.program.datetime_finished = deadline
        self.program.save(update_fields=["datetime_finished"])
        with patch("django.utils.timezone.now", return_value=deadline - timezone.timedelta(microseconds=1)):
            self.assertEqual(self.read().status_code, 404)
        self.private.refresh_from_db()
        self.assertFalse(self.private.is_public)
        with patch("django.utils.timezone.now", return_value=deadline):
            self.assertEqual(self.read().data["count"], 2)
        late = create_project(is_public=False)
        create_program_member(self.program, project=late)
        self.program.publish_projects_after_finish = False
        self.program.save(update_fields=["publish_projects_after_finish"])
        self.assertEqual(self.read().status_code, 404)
        late.refresh_from_db()
        self.assertFalse(late.is_public)
        self.program.publish_projects_after_finish = True
        self.program.save(update_fields=["publish_projects_after_finish"])
        self.assertEqual(self.read().data["count"], 3)
        late.refresh_from_db()
        self.assertTrue(late.is_public)

    def test_program_page_and_direct_project_link_publish_without_list_visit(self):
        self.assertEqual(self.read(f"/projects/{self.private.pk}/").status_code, 200)
        self.private.refresh_from_db()
        self.assertTrue(self.private.is_public)
        late = create_project(is_public=False)
        create_program_member(self.program, project=late)
        self.assertEqual(self.read(f"/programs/{self.program.pk}/").status_code, 200)
        late.refresh_from_db()
        self.assertTrue(late.is_public)

    def test_member_and_unregistered_detail_expose_server_capability(self):
        for registered in (False, True):
            with self.subTest(registered=registered):
                if registered:
                    create_program_member(self.program, user=self.user)
                    self.client.force_authenticate(self.user)
                response = self.read(f"/programs/{self.program.pk}/")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data["published_projects_available"])

    def test_flag_future_draft_and_solution_mode_do_not_open_legacy_reader(self):
        cases = [
            {"publish_projects_after_finish": False},
            {"datetime_finished": timezone.now() + timezone.timedelta(days=1)},
            {"draft": True},
            {"solution_storage_mode": "solution"},
        ]
        for values in cases:
            with self.subTest(values=values):
                program = create_partner_program(
                    publish_projects_after_finish=True,
                    datetime_finished=timezone.now() - timezone.timedelta(days=1),
                )
                hidden = create_project(is_public=False)
                PartnerProgramProject.objects.create(partner_program=program, project=hidden)
                for key, value in values.items():
                    setattr(program, key, value)
                program.save()
                self.assertEqual(
                    self.read(f"/programs/{program.pk}/published-projects/").status_code,
                    404,
                )
                self.assertEqual(self.read(f"/programs/{program.pk}/").status_code, 200)
                self.assertIn(self.read(f"/projects/{hidden.pk}/").status_code, (401, 403))
                hidden.refresh_from_db()
                self.assertFalse(hidden.is_public)

    def test_profile_source_search_pagination_and_duplicate_links(self):
        create_program_member(self.program, user=self.user, project=self.public)
        extra = create_project(is_public=True, name="Public second")
        create_program_member(self.program, project=extra)
        response = self.read(self.url + "?search=Public&limit=1&offset=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual([row["id"] for row in response.data["results"]], [extra.pk])

    def test_private_manager_list_filters_and_exports_keep_permissions(self):
        self.client.force_authenticate(self.user)
        for suffix in ("projects/", "export-projects/"):
            self.assertEqual(
                self.read(f"/programs/{self.program.pk}/{suffix}").status_code, 403
            )
        self.assertEqual(
            self.client.post(
                f"/programs/{self.program.pk}/projects/filter/",
                {},
                format="json",
                secure=True,
            ).status_code,
            403,
        )
        self.assertEqual(self.client.post(self.url, {}, secure=True).status_code, 405)

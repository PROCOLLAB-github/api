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

    def test_anonymous_reader_only_returns_published_non_draft_projects(self):
        response = self.read()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.data["results"]], [self.public.pk]
        )
        self.assertNotIn("program_data", response.data["results"][0])
        self.assertNotIn("scores", response.data["results"][0])
        self.private.refresh_from_db()
        self.assertFalse(self.private.is_public)  # GET does not publish.

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
                for key, value in values.items():
                    setattr(program, key, value)
                program.save()
                self.assertEqual(
                    self.read(f"/programs/{program.pk}/published-projects/").status_code,
                    404,
                )

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

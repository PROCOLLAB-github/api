"""Program analytics links must open project detail without granting write access."""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from invites.models import Invite
from project_rates.tests.helpers import create_rate_expert
from projects.serializers import ProjectDetailSerializer, PartnerProgramProjectSerializer

from .helpers import (
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
    link_project_to_program,
)


class ProgramProjectDetailAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.program = create_partner_program(is_competitive=True)
        cls.other_program = create_partner_program(is_competitive=True)
        cls.project = create_project(draft=True, is_public=False)
        cls.collaborator = create_collaborator(cls.project).user
        cls.link = link_project_to_program(cls.project, cls.program)
        cls.manager = create_user(prefix="detail-manager")
        cls.program.managers.add(cls.manager)
        cls.expert = create_rate_expert(program=cls.program)
        cls.other_manager = create_user(prefix="other-manager")
        cls.other_program.managers.add(cls.other_manager)
        cls.other_expert = create_rate_expert(program=cls.other_program)
        cls.staff = create_user(prefix="detail-staff")
        cls.staff.is_staff = True
        cls.staff.save(update_fields=["is_staff"])
        cls.superuser = create_user(prefix="detail-superuser")
        cls.superuser.is_superuser = True
        cls.superuser.save(update_fields=["is_superuser"])
        cls.invited = create_user(prefix="detail-invited")
        Invite.objects.create(project=cls.project, user=cls.invited)
        cls.outsider = create_user(prefix="detail-outsider")

    def setUp(self):
        self.client = APIClient()
        self.url = f"/projects/{self.project.pk}/"

    def assert_readable(self, user):
        self.client.force_authenticate(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["id"], self.project.pk)

    def test_linked_manager_can_read_private_draft(self):
        self.assert_readable(self.manager)

    def test_linked_expert_can_read_private_draft(self):
        self.assert_readable(self.expert)

    def test_linked_manager_safe_methods_remain_read_only(self):
        self.client.force_authenticate(self.manager)
        for method in ("head", "options"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(self.url).status_code, 200)

    def test_staff_without_superuser_can_read_private_draft(self):
        self.assertFalse(self.staff.is_superuser)
        self.assert_readable(self.staff)

    def test_superuser_without_staff_can_read_private_draft(self):
        self.assertFalse(self.superuser.is_staff)
        self.assert_readable(self.superuser)

    def test_existing_project_roles_can_read_private_draft(self):
        for user in (self.project.leader, self.collaborator, self.invited):
            with self.subTest(user=user.pk):
                self.assert_readable(user)

    def test_unrelated_and_other_program_roles_cannot_read_private_draft(self):
        for user in (self.outsider, self.other_manager, self.other_expert):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_cannot_read_private_draft(self):
        self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_public_flag_does_not_expose_draft_to_outsiders(self):
        self.project.is_public = True
        self.project.save(update_fields=["is_public"])
        for user in (None, self.outsider, self.other_manager, self.other_expert):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                self.assertIn(self.client.get(self.url).status_code, (401, 403))
        self.assert_readable(self.manager)
        self.assert_readable(self.expert)

    def test_published_private_and_public_visibility_is_preserved(self):
        self.project.draft = False
        self.project.save(update_fields=["draft"])
        self.assert_readable(self.manager)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.project.is_public = True
        self.project.save(update_fields=["is_public"])
        self.assert_readable(self.outsider)
        self.assert_readable(None)

    def test_read_roles_do_not_gain_write_access_to_drafts_or_published_projects(self):
        original_name = self.project.name
        for draft in (True, False):
            self.project.draft = draft
            self.project.save(update_fields=["draft"])
            for user in (self.manager, self.expert, self.staff, self.superuser):
                self.client.force_authenticate(user)
                for method in ("patch", "put", "delete"):
                    with self.subTest(draft=draft, user=user.pk, method=method):
                        response = getattr(self.client, method)(
                            self.url, {"name": "Unauthorized change"}, format="json"
                        )
                        self.assertEqual(response.status_code, 403, response.data)
                        self.project.refresh_from_db()
                        self.assertEqual(self.project.name, original_name)

    def test_manager_opens_exact_project_from_attention_with_one_or_two_links(self):
        self.client.force_authenticate(self.manager)
        self.assertNotEqual(self.project.leader_id, self.manager.pk)
        self.assertFalse(self.project.collaborator_set.filter(user=self.manager).exists())
        self.assertFalse(self.project.invite_set.filter(user=self.manager).exists())
        for count in (1, 2):
            with self.subTest(program_links=count):
                if count == 2:
                    link_project_to_program(self.project, self.other_program)
                attention = self.client.get(
                    f"/programs/{self.program.pk}/manager-overview/projects-not-submitted/"
                )
                self.assertEqual(attention.status_code, 200, attention.data)
                self.assertEqual(attention.data["count"], 1)
                row = attention.data["results"][0]
                self.assertEqual(row["program_project_id"], self.link.pk)
                detail = self.client.get(f"/projects/{row['project']['id']}/")
                self.assertEqual(detail.status_code, 200, detail.data)
                self.assertEqual(detail.data["id"], self.project.pk)
                self.assertEqual(
                    detail.data["partner_program"]["program_link_id"], self.link.pk
                )
        self.assertFalse(self.project.collaborator_set.filter(user=self.manager).exists())
        self.assertFalse(self.project.invite_set.filter(user=self.manager).exists())


class ProjectDetailProgramLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.project = create_project(draft=False, is_public=True)
        # Create programs in the opposite order to links: selection is by link pk.
        cls.later_link_program = create_partner_program(name="Created first")
        cls.first_link_program = create_partner_program(name="Linked first")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.project.leader)
        self.url = f"/projects/{self.project.pk}/"

    def detail(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def test_no_program_links_returns_null(self):
        self.assertIsNone(self.detail()["partner_program"])

    def test_single_program_link_preserves_legacy_contract(self):
        link = link_project_to_program(self.project, self.first_link_program)
        self.assertEqual(
            self.detail()["partner_program"], PartnerProgramProjectSerializer(link).data
        )

    def test_multiple_links_return_earliest_link_deterministically(self):
        first = link_project_to_program(self.project, self.first_link_program)
        link_project_to_program(self.project, self.later_link_program, submitted=True)
        for _ in range(2):
            data = self.detail()["partner_program"]
            self.assertEqual(data, PartnerProgramProjectSerializer(first).data)
            self.assertEqual(data["program_id"], self.first_link_program.pk)
            self.assertFalse(data["is_submitted"])

    def test_single_link_serializer_uses_one_join_and_existing_field_queries(self):
        link_project_to_program(self.project, self.first_link_program)
        # Existing contract: joined link/program, program fields, field values.
        with self.assertNumQueries(3):
            ProjectDetailSerializer().get_partner_program(self.project)

    def test_detail_queries_do_not_grow_with_number_of_program_links(self):
        link_project_to_program(self.project, self.first_link_program)
        self.detail()  # Warm only the existing View record and ContentType cache.
        ContentType.objects.get_for_model(self.project)
        cache.clear()
        with CaptureQueriesContext(connection) as single:
            self.detail()
        for _ in range(7):
            link_project_to_program(self.project, create_partner_program())
        cache.clear()
        with CaptureQueriesContext(connection) as multiple:
            self.detail()
        self.assertEqual(len(multiple), len(single))
        # Only one selected program is serialized, irrespective of link count.
        with self.assertNumQueries(3):
            ProjectDetailSerializer().get_partner_program(self.project)

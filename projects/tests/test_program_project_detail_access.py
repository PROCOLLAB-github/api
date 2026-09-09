"""Production project reads: scoped program data without new write grants."""

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient, APIRequestFactory

from invites.models import Invite
from partner_programs.models import PartnerProgramFieldValue
from partner_programs.tests.helpers import create_program_field
from project_rates.tests.helpers import create_rate_expert
from projects.permissions import HasInvolvementInProjectOrReadOnly
from projects.serializers import PartnerProgramProjectSerializer

from .helpers import (
    add_program_member,
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
    link_project_to_program,
)


class ProgramProjectDetailAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.program_a = create_partner_program(is_competitive=True)
        cls.program_b = create_partner_program(is_competitive=True)
        cls.foreign_program = create_partner_program()
        cls.project = create_project(draft=True, is_public=False)
        cls.link_a = link_project_to_program(cls.project, cls.program_a)
        cls.field_a = create_program_field(cls.program_a, name="answer_a")
        cls.value_a = PartnerProgramFieldValue.objects.create(
            program_project=cls.link_a, field=cls.field_a, value_text="Answer A"
        )
        cls.manager_a = create_user(prefix="manager-a")
        cls.program_a.managers.add(cls.manager_a)
        cls.expert_a = create_rate_expert(program=cls.program_a)
        cls.manager_b = create_user(prefix="manager-b")
        cls.program_b.managers.add(cls.manager_b)
        cls.expert_b = create_rate_expert(program=cls.program_b)
        cls.foreign_manager = create_user(prefix="foreign-manager")
        cls.foreign_program.managers.add(cls.foreign_manager)
        cls.foreign_expert = create_rate_expert(program=cls.foreign_program)
        cls.collaborator = create_user(prefix="collaborator")
        add_program_member(cls.program_a, cls.collaborator)
        create_collaborator(cls.project, user=cls.collaborator)
        cls.invited = create_user(prefix="invited")
        Invite.objects.create(project=cls.project, user=cls.invited)
        cls.staff = create_user(prefix="staff")
        cls.staff.is_staff = True
        cls.staff.save(update_fields=["is_staff"])
        cls.superuser = create_user(prefix="superuser")
        cls.superuser.is_superuser = True
        cls.superuser.save(update_fields=["is_superuser"])
        cls.outsider = create_user(prefix="outsider")

    def setUp(self):
        self.client = APIClient()
        self.url = f"/projects/{self.project.pk}/"

    def detail(self, user):
        self.client.force_authenticate(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def add_second_link(self):
        link = link_project_to_program(self.project, self.program_b)
        field = create_program_field(self.program_b, name="answer_b")
        PartnerProgramFieldValue.objects.create(
            program_project=link, field=field, value_text="Private answer B"
        )
        link.submitted = True
        link.save(update_fields=["submitted"])
        return link

    def test_linked_program_and_project_roles_can_read_private_draft(self):
        for user in (
            self.manager_a,
            self.expert_a,
            self.project.leader,
            self.collaborator,
            self.invited,
            self.staff,
            self.superuser,
        ):
            with self.subTest(user=user.pk):
                self.assertEqual(self.detail(user)["id"], self.project.pk)

    def test_linked_manager_and_expert_safe_methods(self):
        for user in (self.manager_a, self.expert_a):
            self.client.force_authenticate(user)
            for method in ("get", "head", "options"):
                with self.subTest(user=user.pk, method=method):
                    self.assertEqual(
                        getattr(self.client, method)(self.url).status_code, 200
                    )

    def test_private_draft_rejects_unrelated_readers(self):
        for user in (self.outsider, self.foreign_manager, self.foreign_expert):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_public_flag_does_not_make_draft_readable_to_outsiders(self):
        self.project.is_public = True
        self.project.save(update_fields=["is_public"])
        for user, expected in ((None, 401), (self.outsider, 403)):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, expected)
        self.detail(self.manager_a)
        self.detail(self.expert_a)

    def test_read_grants_do_not_allow_writes(self):
        original_name = self.project.name
        for draft, public in ((True, False), (False, False), (False, True)):
            self.project.draft, self.project.is_public = draft, public
            self.project.save(update_fields=["draft", "is_public"])
            for user in (self.manager_a, self.expert_a, self.staff, self.superuser):
                self.client.force_authenticate(user)
                for method in ("patch", "put", "delete"):
                    with self.subTest(
                        draft=draft, public=public, user=user.pk, method=method
                    ):
                        response = getattr(self.client, method)(
                            self.url, {"name": "Unauthorized change"}, format="json"
                        )
                        self.assertEqual(response.status_code, 403, response.data)
                        self.project.refresh_from_db()
                        self.assertEqual(self.project.name, original_name)
                        self.assertTrue(
                            self.project.program_links.filter(pk=self.link_a.pk).exists()
                        )

    def test_independent_project_write_permissions_are_preserved(self):
        add_program_member(self.program_a, self.manager_a)
        create_collaborator(self.project, user=self.manager_a)
        Invite.objects.create(project=self.project, user=self.expert_a)
        factory = APIRequestFactory()
        permission = HasInvolvementInProjectOrReadOnly()
        for draft in (True, False):
            self.project.draft = draft
            for user in (self.project.leader, self.manager_a, self.expert_a):
                for method in ("patch", "put", "delete"):
                    with self.subTest(draft=draft, user=user.pk, method=method):
                        request = getattr(factory, method)(self.url)
                        request.user = user
                        self.assertEqual(
                            permission.has_object_permission(request, None, self.project),
                            draft or user.pk == self.project.leader_id,
                        )

    def test_manager_with_independent_collaborator_role_can_patch_draft(self):
        add_program_member(self.program_a, self.manager_a)
        create_collaborator(self.project, user=self.manager_a)
        self.client.force_authenticate(self.manager_a)
        response = self.client.patch(self.url, {"name": "Allowed change"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Allowed change")

    def test_single_link_preserves_full_nested_contract(self):
        expected = PartnerProgramProjectSerializer(self.link_a).data
        self.assertEqual(self.detail(self.manager_a)["partner_program"], expected)
        self.assertEqual(self.detail(self.project.leader)["partner_program"], expected)

    def test_no_links_returns_null(self):
        self.link_a.delete()
        self.assertIsNone(self.detail(self.project.leader)["partner_program"])

    def test_program_roles_only_receive_their_link_and_fields(self):
        link_b = self.add_second_link()
        for user, link in (
            (self.manager_a, self.link_a),
            (self.expert_a, self.link_a),
            (self.manager_b, link_b),
            (self.expert_b, link_b),
        ):
            with self.subTest(user=user.pk):
                data = self.detail(user)["partner_program"]
                self.assertEqual(data, PartnerProgramProjectSerializer(link).data)
                self.assertEqual(data["program_id"], link.partner_program_id)

    def test_program_role_scope_also_applies_to_public_published_projects(self):
        link_b = self.add_second_link()
        self.project.draft, self.project.is_public = False, True
        self.project.save(update_fields=["draft", "is_public"])
        for user in (self.manager_b, self.expert_b):
            with self.subTest(user=user.pk):
                self.assertEqual(
                    self.detail(user)["partner_program"],
                    PartnerProgramProjectSerializer(link_b).data,
                )

    def test_minimum_eligible_link_not_first_global_or_program_id(self):
        link_b = self.add_second_link()
        # Program A exists first, but its replacement link is created last.
        self.link_a.delete()
        replacement = link_project_to_program(self.project, self.program_a)
        self.program_b.managers.add(self.manager_a)
        self.expert_a.expert.programs.add(self.program_b)
        for user in (self.manager_a, self.expert_a):
            with self.subTest(user=user.pk):
                self.assertEqual(
                    self.detail(user)["partner_program"]["program_link_id"], link_b.pk
                )
        self.program_b.managers.remove(self.manager_a)
        self.expert_a.expert.programs.remove(self.program_b)
        for user in (self.manager_a, self.expert_a):
            with self.subTest(user=user.pk, only_a=True):
                self.assertEqual(
                    self.detail(user)["partner_program"]["program_link_id"],
                    replacement.pk,
                )

    def test_independent_project_roles_use_global_minimum_even_with_program_role(self):
        self.add_second_link()
        for user in (
            self.project.leader,
            self.collaborator,
            self.invited,
            self.staff,
            self.superuser,
        ):
            self.program_b.managers.add(user)
            with self.subTest(user=user.pk):
                self.assertEqual(
                    self.detail(user)["partner_program"],
                    PartnerProgramProjectSerializer(self.link_a).data,
                )

    def test_existing_public_field_exposure_is_preserved(self):
        self.project.draft, self.project.is_public = False, True
        self.project.save(update_fields=["draft", "is_public"])
        expected = PartnerProgramProjectSerializer(self.link_a).data
        self.assertTrue(expected["program_fields"])
        self.assertTrue(expected["program_field_values"])
        for user in (None, self.outsider, self.foreign_manager, self.foreign_expert):
            with self.subTest(user=user):
                self.assertEqual(self.detail(user)["partner_program"], expected)

    def test_published_private_project_stays_private(self):
        self.project.draft = False
        self.project.save(update_fields=["draft"])
        self.detail(self.manager_a)
        self.detail(self.expert_a)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def query_counts(self, users):
        counts = []
        for user in users:
            self.detail(user)  # Warm existing view records and content-type cache.
            ContentType.objects.get_for_model(self.project)
            cache.clear()
            with CaptureQueriesContext(connection) as queries:
                self.detail(user)
            counts.append(len(queries))
        return counts

    def test_detail_query_count_is_constant_for_one_and_eight_links(self):
        users = (self.project.leader, self.manager_a, self.expert_a)
        single = self.query_counts(users)
        for _ in range(7):
            program = create_partner_program()
            program.managers.add(self.manager_a)
            self.expert_a.expert.programs.add(program)
            link = link_project_to_program(self.project, program)
            field = create_program_field(program)
            PartnerProgramFieldValue.objects.create(
                program_project=link, field=field, value_text="Other program answer"
            )
        self.assertEqual(self.project.program_links.count(), 8)
        self.assertEqual(self.query_counts(users), single)

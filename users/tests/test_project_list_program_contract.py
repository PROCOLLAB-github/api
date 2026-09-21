"""Регрессии компактного контракта «Моих проектов» и выбора legacy-связи."""

from django.core.cache import cache
from django.db import connection
from django.db.models import Prefetch
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.services import get_views_count
from partner_programs.models import PartnerProgramProject
from projects.models import Project
from projects.tests.helpers import (
    add_program_member,
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
    link_project_to_program,
)
from users.serializers import UserProjectListSerializer


class UserProjectProgramContractTests(TestCase):
    endpoints = ("/auth/users/projects/", "/auth/users/projects/leader/")

    def setUp(self):
        self.leader = create_user()
        self.project = create_project(leader=self.leader)
        self.client = APIClient()
        self.client.force_authenticate(self.leader)
        cache.clear()

    def list_program(self, endpoint):
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        return response.data["results"][0]["partner_program"]

    def test_no_program_is_null_in_both_lists(self):
        for endpoint in self.endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertIsNone(self.list_program(endpoint))

    def test_compact_contract_preserves_ids_and_authoritative_submission(self):
        link = link_project_to_program(self.project, create_partner_program())
        for submitted in (False, True):
            link.submitted = submitted
            link.save(update_fields=["submitted"])
            for endpoint in self.endpoints:
                with self.subTest(submitted=submitted, endpoint=endpoint):
                    self.assertEqual(
                        self.list_program(endpoint),
                        {
                            "id": link.partner_program_id,
                            "name": link.partner_program.name,
                            "program_link_id": link.pk,
                            "program_id": link.partner_program_id,
                            "is_submitted": submitted,
                        },
                    )

    def create_reversed_links(self):
        """PK связи, порядок её создания и PK программы намеренно не совпадают."""
        earlier_program = create_partner_program()
        later_program = create_partner_program()
        PartnerProgramProject.objects.create(
            pk=20,
            project=self.project,
            partner_program=earlier_program,
            submitted=False,
        )
        return PartnerProgramProject.objects.create(
            pk=10,
            project=self.project,
            partner_program=later_program,
            submitted=True,
        )

    def test_list_and_detail_choose_minimum_link_pk_not_creation_or_program_order(self):
        selected = self.create_reversed_links()
        detail = self.client.get(f"/projects/{self.project.pk}/")
        self.assertEqual(detail.status_code, 200)
        expected = {
            "program_link_id": selected.pk,
            "program_id": selected.partner_program_id,
            "is_submitted": True,
        }
        self.assertEqual(
            {key: detail.data["partner_program"][key] for key in expected}, expected
        )
        for endpoint in self.endpoints:
            with self.subTest(endpoint=endpoint):
                result = self.list_program(endpoint)
                self.assertEqual({key: result[key] for key in expected}, expected)

    def test_reversed_prefetch_and_uncached_lookup_select_same_link(self):
        selected = self.create_reversed_links()
        prefetched = Project.objects.prefetch_related(
            Prefetch(
                "program_links",
                queryset=PartnerProgramProject.objects.select_related(
                    "partner_program"
                ).order_by("-pk"),
            )
        ).get(pk=self.project.pk)
        self.assertEqual(prefetched.program_links.all()[0].pk, 20)
        with self.assertNumQueries(0):
            cached = UserProjectListSerializer.get_partner_program(prefetched)
        with self.assertNumQueries(1):
            uncached = UserProjectListSerializer.get_partner_program(self.project)
        self.assertEqual(cached, uncached)
        self.assertEqual(cached["program_link_id"], selected.pk)
        self.assertIs(cached["is_submitted"], True)

    def test_empty_prefetch_does_not_query_again(self):
        project = Project.objects.prefetch_related("program_links").get(
            pk=self.project.pk
        )
        with self.assertNumQueries(0):
            self.assertIsNone(UserProjectListSerializer.get_partner_program(project))

    def test_leader_and_collaborator_see_identical_lifecycle(self):
        program = create_partner_program()
        link_project_to_program(self.project, program, submitted=True)
        collaborator = create_user()
        add_program_member(program, collaborator)
        create_collaborator(self.project, user=collaborator)
        leader_metadata = self.list_program(self.endpoints[0])
        self.client.force_authenticate(collaborator)
        self.assertEqual(self.list_program(self.endpoints[0]), leader_metadata)
        detail = self.client.get(f"/projects/{self.project.pk}/")
        self.assertEqual(detail.status_code, 200)
        for field in ("program_link_id", "program_id", "is_submitted"):
            self.assertEqual(
                detail.data["partner_program"][field], leader_metadata[field]
            )
        # Чтение метаданных не превращает участника в лидера.
        response = self.client.get(self.endpoints[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"], [])

    def test_unauthenticated_user_cannot_read_my_projects(self):
        self.client.force_authenticate(None)
        for endpoint in self.endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertIn(self.client.get(endpoint).status_code, (401, 403))

    def test_query_count_is_constant_for_1_and_31_projects(self):
        program = create_partner_program()
        link_project_to_program(self.project, program, submitted=True)

        def counts(expected_count):
            # Счётчик просмотров имеет собственный старый кеш. Прогреваем только
            # его, чтобы измерять list/prefetch без посторонних cache miss.
            for project in Project.objects.filter(leader=self.leader):
                get_views_count(project)
            measured = []
            for endpoint in self.endpoints:
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(endpoint, {"limit": 100})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(len(response.data["results"]), expected_count)
                measured.append(len(queries))
            return measured

        one = counts(1)
        for index in range(30):
            project = create_project(leader=self.leader)
            # Смешанный список ловит и N+1 на пустом кеше связей.
            if index % 2 == 0:
                link_project_to_program(project, program, submitted=False)
        thirty_one = counts(31)
        self.assertEqual(one, [3, 3])  # COUNT, страница проектов, JOIN-prefetch связей.
        self.assertEqual(thirty_one, one)

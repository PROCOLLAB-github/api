from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APITestCase

from projects.tests.helpers import (
    create_collaborator,
    create_partner_program,
    create_project,
    create_user,
    link_project_to_program,
)


class ProjectCountViewTests(APITestCase):
    endpoint = "/projects/count/"

    def setUp(self):
        self.user = create_user(prefix="project-count-user")
        self.client.force_authenticate(self.user)

    def get_count(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def test_user_without_projects_has_zero_activity(self):
        self.assertEqual(
            self.get_count(),
            {
                "all": 0,
                "my": 0,
                "my_leader": 0,
                "my_in_program": 0,
                "my_submitted": 0,
            },
        )

    def test_counts_leader_collaborator_and_does_not_duplicate_project(self):
        leader_project = create_project(leader=self.user, draft=False)
        create_collaborator(leader_project, user=self.user)
        collaborator_project = create_project(draft=False)
        create_collaborator(collaborator_project, user=self.user)
        create_project(draft=False)

        count = self.get_count()

        self.assertEqual(count["my"], 2)
        self.assertEqual(count["my_leader"], 1)
        self.assertEqual(count["all"], 3)

    def test_counts_project_lifecycle_by_canonical_program_link(self):
        program = create_partner_program(name="Lifecycle")
        second_program = create_partner_program(name="Lifecycle second")

        create_project(leader=self.user, draft=True)
        create_project(leader=self.user, draft=False)

        in_program = create_project(leader=self.user, draft=False)
        link_project_to_program(in_program, program, submitted=False)

        draft_in_program = create_project(leader=self.user, draft=True)
        link_project_to_program(draft_in_program, program, submitted=False)

        submitted = create_project(leader=self.user, draft=False)
        link_project_to_program(submitted, program, submitted=True)

        submitted_draft = create_project(leader=self.user, draft=True)
        link_project_to_program(submitted_draft, program, submitted=True)

        canonical_not_submitted = create_project(leader=self.user, draft=False)
        link_project_to_program(canonical_not_submitted, program, submitted=False)
        link_project_to_program(canonical_not_submitted, second_program, submitted=True)

        canonical_submitted = create_project(leader=self.user, draft=False)
        link_project_to_program(canonical_submitted, program, submitted=True)
        link_project_to_program(canonical_submitted, second_program, submitted=False)

        count = self.get_count()

        self.assertEqual(count["my"], 8)
        self.assertEqual(count["my_leader"], 8)
        self.assertEqual(count["my_in_program"], 2)
        self.assertEqual(count["my_submitted"], 3)

    def test_ignores_other_users_projects_and_counts_more_than_dashboard_page(self):
        for index in range(17):
            create_project(leader=self.user, name=f"Owned {index}", draft=False)

        collaborator_project = create_project(draft=False)
        create_collaborator(collaborator_project, user=self.user)
        create_project(draft=False)

        count = self.get_count()

        self.assertEqual(count["my"], 18)
        self.assertEqual(count["my_leader"], 17)

    def test_query_count_does_not_grow_with_project_count(self):
        create_project(leader=self.user, draft=False)
        with CaptureQueriesContext(connection) as one_project_queries:
            self.get_count()

        for index in range(30):
            create_project(leader=self.user, name=f"Scale {index}", draft=False)
        with CaptureQueriesContext(connection) as thirty_one_project_queries:
            count = self.get_count()

        self.assertEqual(count["my"], 31)
        self.assertEqual(len(one_project_queries), 1)
        self.assertEqual(
            len(thirty_one_project_queries),
            len(one_project_queries),
        )

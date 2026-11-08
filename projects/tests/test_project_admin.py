from django.test import TestCase
from django.urls import reverse

from .helpers import create_collaborator, create_project, create_staff_user, create_user


class ProjectLeaderFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = create_staff_user()
        cls.leader = create_user()
        cls.draft = create_project(leader=cls.leader, name="Leader draft")
        cls.published = create_project(leader=cls.leader, name="Leader published", draft=False)
        cls.other = create_project(name="Other project")
        create_collaborator(cls.other, user=cls.leader)

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("admin:projects_project_changelist")

    def test_filters_by_leader_id_or_email(self):
        for leader in (str(self.leader.pk), self.leader.email.upper()):
            with self.subTest(leader=leader):
                response = self.client.get(self.url, {"leader": leader})
                self.assertContains(response, 'id="project-leader-filter"')
                self.assertContains(response, "Сбросить фильтр")
                self.assertCountEqual(response.context["cl"].result_list, [self.draft, self.published])

    def test_combines_with_search_and_draft_filter(self):
        response = self.client.get(self.url, {"leader": self.leader.pk, "draft__exact": "1", "q": "Leader"})

        self.assertContains(response, '<input type="hidden" name="draft__exact" value="1">', html=True)
        self.assertContains(response, 'href="?draft__exact=1&amp;q=Leader"')
        self.assertEqual(list(response.context["cl"].result_list), [self.draft])

    def test_invalid_leader_id_returns_no_projects(self):
        response = self.client.get(self.url, {"leader": "9223372036854775808"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["cl"].result_list), [])

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from files.models import UserFile
from partner_programs.models import PartnerProgramMaterial, PartnerProgramUserProfile
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectScore, ProjectExpertAssignment
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator


class ManagementAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = create_user(prefix="management-manager")
        cls.other = create_user(prefix="management-other")
        cls.program = create_partner_program(is_competitive=True)
        cls.program.managers.add(cls.manager)
        cls.foreign = create_partner_program(is_competitive=True)
        cls.foreign.managers.add(cls.other)
        cls.member = create_program_member(
            cls.program,
            user=create_user(first_name="Анна", last_name="Крылова", city="Москва"),
        )
        cls.project = create_project(
            leader=cls.member.user, presentation_address="https://example.com/deck.pdf"
        )
        cls.link = create_program_project(
            cls.program, project=cls.project, submitted=True
        )
        cls.foreign_link = create_program_project(cls.foreign)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def url(self, name="management", **kwargs):
        return reverse(
            "partner_programs:" + name, kwargs={"pk": self.program.pk, **kwargs}
        )

    def test_program_access_is_object_scoped_and_authenticated(self):
        for user, expected in [
            (self.manager, 200),
            (self.other, 403),
            (self.member.user, 403),
            (None, 401),
        ]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url()).status_code, expected)
        self.client.force_authenticate(create_user(is_staff=True))
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_expert_role_does_not_grant_management(self):
        expert = create_rate_expert(program=self.program)
        self.client.force_authenticate(expert)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_all_resources_reject_foreign_manager(self):
        self.client.force_authenticate(self.other)
        endpoints = [
            self.url(),
            self.url("management-participants"),
            self.url("management-projects"),
            self.url("management-team", link_id=self.link.pk),
            self.url("management-evaluation", link_id=self.link.pk),
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 403)
        self.assertEqual(
            self.client.patch(
                self.url("management-settings", section="basic"),
                {"name": "attack"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.url("management-materials"),
                {"title": "attack", "url": "https://example.com"},
                format="json",
            ).status_code,
            403,
        )

    def test_participants_have_email_and_program_registration_and_server_search(self):
        create_program_member(self.foreign, user=self.member.user)
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program, user=None, partner_program_data={}
        )
        response = self.client.get(
            self.url("management-participants"), {"search": "Крылова Анна", "limit": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], self.member.pk)
        self.assertEqual(row["email"], self.member.user.email)
        self.assertEqual(row["registered_at"], self.member.datetime_created)
        by_email = self.client.get(
            self.url("management-participants"), {"search": self.member.user.email}
        )
        self.assertEqual(by_email.data["count"], 1)

    def test_bad_query_is_not_silently_defaulted(self):
        for query in [
            {"limit": 101},
            {"limit": 0},
            {"offset": -1},
            {"offset": "bad"},
            {"search": "a" * 201},
        ]:
            with self.subTest(query=query):
                self.assertEqual(
                    self.client.get(
                        self.url("management-participants"), query
                    ).status_code,
                    400,
                )

    def test_projects_use_link_submission_and_current_program_scores(self):
        expert = create_rate_expert(program=self.foreign)
        criterion = Criteria.objects.create(
            partner_program=self.foreign,
            name="Foreign",
            type="int",
            min_value=0,
            max_value=10,
        )
        ProjectScore.objects.create(
            project=self.project, criteria=criterion, user=expert, value="8"
        )
        response = self.client.get(self.url("management-projects"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["id"], self.link.pk)
        self.assertEqual(row["evaluation_status"], "awaiting_evaluation")
        self.assertEqual(row["presentation_url"], self.project.presentation_address)
        self.assertTrue(row["submitted"])
        self.assertEqual(
            self.client.get(
                self.url("management-projects"), {"submission": "not_submitted"}
            ).data["count"],
            0,
        )

    def test_team_is_read_only_and_scoped_to_link(self):
        member = create_user()
        Collaborator.objects.bulk_create(
            [Collaborator(project=self.project, user=member, role="Разработчик")]
        )
        response = self.client.get(self.url("management-team", link_id=self.link.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [m["id"] for m in response.data["members"]],
            [self.project.leader_id, member.pk],
        )
        self.assertEqual(
            self.client.get(
                self.url("management-team", link_id=self.foreign_link.pk)
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                self.url("management-team", link_id=self.link.pk), {}
            ).status_code,
            405,
        )

    def test_manager_can_read_scores_but_cannot_become_expert(self):
        expert = create_rate_expert(program=self.program)
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Точность",
            type="int",
            min_value=0,
            max_value=10,
        )
        ProjectScore.objects.create(
            project=self.project, criteria=criterion, user=expert, value="7"
        )
        response = self.client.get(
            self.url("management-evaluation", link_id=self.link.pk)
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["can_rate"])
        self.assertEqual(response.data["experts"][0]["id"], expert.pk)
        self.assertEqual(
            self.client.get(
                self.url("management-evaluation", link_id=self.foreign_link.pk)
            ).status_code,
            404,
        )

    def test_existing_manager_expert_can_rate_only_assigned_submitted_project(self):
        expert = create_rate_expert(program=self.program)
        self.program.managers.add(expert)
        self.program.is_distributed_evaluation = True
        self.program.save()
        self.client.force_authenticate(expert)
        url = self.url("management-evaluation", link_id=self.link.pk)
        self.assertFalse(self.client.get(url).data["can_rate"])
        ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=self.project, expert=expert.expert
        )
        self.assertTrue(self.client.get(url).data["can_rate"])
        unsubmitted = create_program_project(
            self.program, project=create_project(leader=self.member.user), submitted=False
        )
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=unsubmitted.project,
            expert=expert.expert,
        )
        self.assertFalse(
            self.client.get(
                self.url("management-evaluation", link_id=unsubmitted.pk)
            ).data["can_rate"]
        )

    def version(self):
        return self.client.get(self.url()).data["updated_at"].isoformat()

    def test_basic_save_is_whitelisted_and_optimistic(self):
        url = self.url("management-settings", section="basic")
        version = self.version()
        response = self.client.patch(
            url, {"name": "Новое имя", "expected_updated_at": version}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["name"], "Новое имя")
        stale = self.client.patch(
            url,
            {"name": "Потерянная запись", "expected_updated_at": version},
            format="json",
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.data["code"], "stale_settings")
        for field, value in [
            ("managers", [self.other.pk]),
            ("draft", True),
            ("is_competitive", False),
        ]:
            with self.subTest(field=field):
                self.assertEqual(
                    self.client.patch(
                        url,
                        {field: value, "expected_updated_at": self.version()},
                        format="json",
                    ).status_code,
                    400,
                )

    def test_reopening_deadline_requires_confirmation_and_preserves_fallback(self):
        self.program.datetime_registration_ends = timezone.now() - timedelta(days=2)
        self.program.datetime_project_submission_ends = None
        self.program.save()
        url = self.url("management-settings", section="dates")
        payload = {
            "datetime_registration_ends": (
                timezone.now() + timedelta(days=2)
            ).isoformat(),
            "expected_updated_at": self.version(),
        }
        response = self.client.patch(url, payload, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "reopen_confirmation_required")
        self.program.refresh_from_db()
        self.assertLess(self.program.datetime_registration_ends, timezone.now())
        payload["confirm_reopen"] = True
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 200)
        self.program.refresh_from_db()
        self.assertEqual(
            self.program.get_project_submission_deadline(),
            self.program.datetime_registration_ends,
        )

    def test_material_file_ownership_and_delete_keeps_source(self):
        owned = UserFile.objects.create(
            link="https://example.com/own.pdf", user=self.manager
        )
        other = UserFile.objects.create(
            link="https://example.com/other.pdf", user=self.other
        )
        url = self.url("management-materials")
        self.assertEqual(
            self.client.post(
                url, {"title": "Чужой", "file": other.link}, format="json"
            ).status_code,
            400,
        )
        response = self.client.post(
            url, {"title": "Свой", "file": owned.link}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        material = PartnerProgramMaterial.objects.get(pk=response.data["id"])
        delete_url = self.url("management-material", material_id=material.pk)
        self.assertEqual(self.client.delete(delete_url).status_code, 400)
        self.assertEqual(
            self.client.delete(
                delete_url, {"expected_updated_at": "2000-01-01T00:00:00Z"}
            ).status_code,
            400,
        )
        response = self.client.delete(
            delete_url
            + "?expected_updated_at="
            + material.datetime_updated.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        )
        self.assertEqual(response.status_code, 204, response.data)
        self.assertTrue(UserFile.objects.filter(pk=owned.pk).exists())

    def test_material_update_is_scoped_and_conflict_checked(self):
        material = PartnerProgramMaterial.objects.create(
            program=self.program, title="Правила", url="https://example.com/rules"
        )
        url = self.url("management-material", material_id=material.pk)
        payload = {
            "title": "Правила 2",
            "url": "https://example.com/rules-2",
            "file": None,
            "expected_updated_at": material.datetime_updated.isoformat(),
        }
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 409)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.patch(url, payload, format="json").status_code, 403)

    def test_settings_and_materials_reject_wrong_methods(self):
        self.assertEqual(
            self.client.get(self.url("management-settings", section="basic")).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(self.url("management-material", material_id=1)).status_code,
            405,
        )

    def test_distributed_evaluation_uses_completed_real_assignments(self):
        self.program.is_distributed_evaluation = True
        self.program.max_project_rates = 2
        self.program.save()
        Criteria.objects.filter(partner_program=self.program).delete()
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Точность",
            type="int",
            min_value=0,
            max_value=10,
        )
        first = create_rate_expert(program=self.program)
        second = create_rate_expert(program=self.program)
        for user in (first, second):
            ProjectExpertAssignment.objects.create(
                partner_program=self.program, project=self.project, expert=user.expert
            )
        ProjectScore.objects.create(
            project=self.project, criteria=criterion, user=first, value="0"
        )
        row = self.client.get(self.url("management-projects")).data["results"][0]
        self.assertEqual(
            (
                row["evaluation_status"],
                row["assignments_completed"],
                row["assignments_total"],
            ),
            ("partially_evaluated", 1, 2),
        )
        ProjectScore.objects.create(
            project=self.project, criteria=criterion, user=second, value="8"
        )
        self.assertEqual(
            self.client.get(self.url("management-projects")).data["results"][0][
                "evaluation_status"
            ],
            "evaluated",
        )

    def test_noncompetitive_evaluation_is_not_applicable(self):
        self.program.is_competitive = False
        self.program.save()
        response = self.client.get(self.url("management-projects"))
        self.assertEqual(
            response.data["results"][0]["evaluation_status"], "not_applicable"
        )

    def test_pagination_uses_profiles_of_this_program_only(self):
        second = create_program_member(self.program)
        create_program_member(self.foreign)
        response = self.client.get(
            self.url("management-participants"), {"limit": 1, "offset": 1}
        )
        self.assertEqual(response.data["count"], 2)
        self.assertEqual([row["id"] for row in response.data["results"]], [second.pk])

    def test_file_material_can_be_changed_to_link_without_deleting_file(self):
        file = UserFile.objects.create(
            link="https://example.com/retained.pdf", user=self.manager
        )
        material = PartnerProgramMaterial.objects.create(
            program=self.program, title="Файл", file=file
        )
        response = self.client.patch(
            self.url("management-material", material_id=material.pk),
            {
                "title": "Ссылка",
                "file": None,
                "url": "https://example.com/rules",
                "expected_updated_at": material.datetime_updated.isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        material.refresh_from_db()
        self.assertIsNone(material.file_id)
        self.assertTrue(UserFile.objects.filter(pk=file.pk).exists())

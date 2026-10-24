from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
)
from project_rates.criteria_policy import revision
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import (
    create_rate_criteria,
    create_rate_expert,
    create_rate_program,
    create_rate_project,
    create_rate_user,
    link_project_to_program,
)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ScoringWorkspaceTests(TestCase):
    def setUp(self):
        self.program = create_rate_program(
            is_competitive=True,
            is_distributed_evaluation=True,
            required_evaluators=2,
            datetime_evaluation_ends=timezone.now() + timedelta(days=2),
        )
        self.user = create_rate_expert(program=self.program)
        self.number = create_rate_criteria(self.program, min_value=0, max_value=10)
        self.boolean = create_rate_criteria(self.program, type="bool")
        self.comment = self.program.criterias.get(type="str")
        self.project = self.assign("Main")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/rate-project/{self.program.pk}"

    def assign(self, name):
        project = create_rate_project(name=name)
        self.program.users.add(
            project.leader, through_defaults={"partner_program_data": {}}
        )
        link = link_project_to_program(self.program, project)
        link.submitted = True
        link.save()
        ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=project,
            expert=self.user.expert,
        )
        return project

    def complete(self, project, user=None):
        for criterion, value in [
            (self.number, "0"),
            (self.boolean, "False"),
            (self.comment, ""),
        ]:
            ProjectScore.objects.create(
                project=project, criteria=criterion, user=user or self.user, value=value
            )

    def page(self, **query):
        response = self.client.get(self.url, {"assigned_only": 1, **query})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.data

    def test_own_status_ignores_another_experts_scores(self):
        self.complete(self.project, create_rate_expert(program=self.program))
        data = self.page(evaluation_status="pending")
        self.assertEqual(data["evaluation_counts"], {"pending": 1, "completed": 0})
        self.assertFalse(data["results"][0]["scored"])
        self.assertEqual(self.page(evaluation_status="completed")["results"], [])

    def test_status_ignores_scores_from_another_program_on_same_project(self):
        other = create_rate_program()
        # Historical shared-project link, before team-freeze rules were introduced.
        PartnerProgramProject.objects.bulk_create(
            [
                PartnerProgramProject(
                    partner_program=other, project=self.project, submitted=True
                )
            ]
        )
        criterion = create_rate_criteria(other)
        ProjectScore.objects.create(
            project=self.project, user=self.user, criteria=criterion, value="8"
        )
        self.assertEqual(self.page(evaluation_status="pending")["count"], 1)

    def test_counts_are_before_status_and_pagination_but_after_search(self):
        self.complete(self.project)
        self.assign("Second")
        data = self.page(evaluation_status="completed", limit=1)
        self.assertEqual(data["evaluation_counts"], {"pending": 1, "completed": 1})
        self.assertTrue(data["results"][0]["scored"])
        filtered = self.page(name__contains="Main", evaluation_status="pending")
        self.assertEqual(filtered["count"], 0)
        self.assertEqual(filtered["evaluation_counts"], {"pending": 0, "completed": 1})

    def test_configured_post_filters_scope_both_counts(self):
        other = self.assign("Other")
        self.complete(self.project)
        field = PartnerProgramField.objects.create(
            partner_program=self.program,
            name="case",
            label="Кейс",
            field_type="select",
            options="A|B",
            show_filter=True,
            is_required=True,
        )
        # Fixture values predate submission; current editing rules freeze them afterwards.
        PartnerProgramFieldValue.objects.bulk_create(
            [
                PartnerProgramFieldValue(
                    program_project=self.program.program_projects.get(
                        project=self.project
                    ),
                    field=field,
                    value_text="A",
                ),
                PartnerProgramFieldValue(
                    program_project=self.program.program_projects.get(project=other),
                    field=field,
                    value_text="B",
                ),
            ]
        )
        response = self.client.post(
            self.url + "?assigned_only=1&evaluation_status=completed",
            {"filters": {"case": ["B"]}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["evaluation_counts"], {"pending": 1, "completed": 0}
        )
        self.assertEqual(response.data["results"], [])

    def test_zero_false_and_optional_empty_comment_are_completed(self):
        self.complete(self.project)
        self.assertEqual(self.page(evaluation_status="completed")["count"], 1)

    def test_non_numeric_only_program_is_completed(self):
        self.number.delete()
        for criterion, value in [(self.boolean, "False"), (self.comment, "")]:
            ProjectScore.objects.create(
                project=self.project, criteria=criterion, user=self.user, value=value
            )
        self.assertEqual(self.page(evaluation_status="completed")["count"], 1)

    def test_unsubmitted_link_is_not_completed(self):
        self.complete(self.project)
        self.program.program_projects.filter(project=self.project).update(submitted=False)
        self.assertEqual(self.page(evaluation_status="pending")["count"], 1)

    def test_no_criteria_never_means_completed(self):
        self.program.criterias.all().delete()
        self.assertEqual(self.page(evaluation_status="completed")["count"], 0)

    def test_unassigned_foreign_project_is_not_revealed(self):
        project = create_rate_project()
        self.program.users.add(
            project.leader, through_defaults={"partner_program_data": {}}
        )
        link_project_to_program(self.program, project)
        self.assertEqual(self.page(project_id=project.pk)["results"], [])

    def test_legacy_any_expert_filter_keeps_original_meaning(self):
        self.complete(self.project, create_rate_expert(program=self.program))
        data = self.page(is_rated_by_expert="true", evaluation_status="pending")
        self.assertEqual(data["count"], 1)

    def test_invalid_status_and_missing_permissions(self):
        self.assertEqual(
            self.client.get(self.url, {"evaluation_status": "draft"}).status_code, 400
        )
        self.client.force_authenticate(create_rate_user())
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url).status_code, [401, 403])

    @patch("project_rates.services._send_project_rated_email")
    def test_long_comment_is_saved_atomically_and_overflow_does_not_change_scores(
        self, _email
    ):
        def payload(comment, points=0):
            self.program.refresh_from_db()
            return {
                "expected_revision": revision(self.program),
                "scores": [
                    {"criterion_id": self.number.pk, "value": points},
                    {"criterion_id": self.boolean.pk, "value": "False"},
                    {"criterion_id": self.comment.pk, "value": comment},
                ],
            }

        response = self.client.post(
            f"/rate-project/rate/{self.project.pk}", payload("я" * 1000), format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            ProjectScore.objects.get(criteria=self.comment, user=self.user).value,
            "я" * 1000,
        )
        response = self.client.post(
            f"/rate-project/rate/{self.project.pk}", payload("я" * 1001, 5), format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            ProjectScore.objects.get(criteria=self.number, user=self.user).value, "0"
        )
        self.assertEqual(
            ProjectScore.objects.get(criteria=self.comment, user=self.user).value,
            "я" * 1000,
        )

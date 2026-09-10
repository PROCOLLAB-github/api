from copy import deepcopy

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from invites.models import Invite
from partner_programs.models import (
    Application,
    Evaluation,
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamMember,
)
from partner_programs.serializers.project_analytics import (
    ProjectAnalyticsSerializer,
    ProjectCaseAnalyticsSerializer,
)
from partner_programs.services.project_case_analytics import (
    build_project_case_analytics,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.tests.test_case_fields import create_case_field
from project_rates.models import ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator


class ProjectCaseAnalyticsFixture:
    def setUp(self):
        super().setUp()
        self.program = create_partner_program(is_competitive=True)
        self.manager = create_user(password=None)
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def overview(self, program=None):
        response = self.client.get(
            reverse(
                "partner_programs:project-analytics",
                kwargs={"program_id": (program or self.program).pk},
            )
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_reconciled(response.json())
        return response.json()

    def link(
        self,
        field=None,
        value=None,
        *,
        program=None,
        submitted=False,
        project=None,
    ):
        program = program or self.program
        link = create_program_project(
            program, project=project or create_project(), submitted=submitted
        )
        if field is not None and value is not None:
            # Seed historical invalid values without weakening current write guards.
            PartnerProgramFieldValue.objects.bulk_create(
                [
                    PartnerProgramFieldValue(
                        program_project=link, field=field, value_text=value
                    )
                ]
            )
        return link

    @staticmethod
    def metrics(projects, submitted, participants=0):
        return {
            "participants_total": participants,
            "projects_total": projects,
            "not_submitted": projects - submitted,
            "submitted": submitted,
        }

    def assert_reconciled(self, overview):
        buckets = [*overview["cases"]["items"], overview["cases"]["without_case"]]
        for bucket in buckets:
            self.assertEqual(
                bucket["projects_total"],
                bucket["not_submitted"] + bucket["submitted"],
            )
        for metric, funnel_metric in (
            ("projects_total", "created"),
            ("submitted", "submitted"),
            ("not_submitted", "not_submitted"),
        ):
            self.assertEqual(
                sum(bucket[metric] for bucket in buckets),
                overview["solution_funnel"][funnel_metric],
            )


class ProjectCaseAnalyticsTests(ProjectCaseAnalyticsFixture, TestCase):
    def test_options_keep_configuration_order_zero_rows_and_reconcile(self):
        field = create_case_field(self.program, options=["Case C", "Case A", "Case B"])
        self.link(field, "Case A", submitted=True)
        self.link(field, "Case A")
        self.link(field, "Case B", submitted=True)
        self.link()
        self.link(field, "Obsolete")
        cases = self.overview()["cases"]
        self.assertEqual(
            cases,
            {
                "configured": True,
                "submission_applicable": True,
                "items": [
                    {"name": "Case C", **self.metrics(0, 0)},
                    {"name": "Case A", **self.metrics(2, 1)},
                    {"name": "Case B", **self.metrics(1, 1)},
                ],
                "without_case": self.metrics(2, 0),
            },
        )

    def test_only_exact_system_name_identifies_case_without_flag_heuristics(self):
        for name in ("Case", "CASE", "Кейс", "case_name", "cases"):
            program = create_partner_program(is_competitive=True)
            program.managers.add(self.manager)
            field = create_program_field(
                program,
                name=name,
                label="Кейс",
                field_type="select",
                options=["A"],
                show_filter=True,
            )
            self.link(field, "A", program=program)
            with self.subTest(name=name):
                cases = self.overview(program)["cases"]
                self.assertFalse(cases["configured"])
                self.assertEqual(cases["items"], [])
                self.assertEqual(cases["without_case"], self.metrics(1, 0))

        field = create_case_field(self.program, label="Unrelated label")
        self.link(field, "A")
        PartnerProgramField.objects.filter(pk=field.pk).update(
            field_type="text", is_required=False, show_filter=False
        )
        cases = self.overview()["cases"]
        self.assertTrue(cases["configured"])
        self.assertEqual(cases["items"][0]["projects_total"], 1)

    def test_missing_blank_whitespace_obsolete_and_nonexact_values_are_without_case(self):
        field = create_case_field(self.program)
        for index, value in enumerate((None, "", "  ", "Legacy", "a", " A ")):
            self.link(field, value, submitted=index % 2 == 0)
        cases = self.overview()["cases"]
        self.assertEqual(cases["without_case"], self.metrics(6, 3))
        self.assertTrue(all(item["projects_total"] == 0 for item in cases["items"]))

    def test_absent_definition_places_every_link_and_team_participant_without_case(self):
        user = create_user(password=None)
        create_program_member(self.program, user=user)
        for index in range(4):
            self.link(project=create_project(leader=user), submitted=index < 2)
        self.assertEqual(
            self.overview()["cases"],
            {
                "configured": False,
                "submission_applicable": True,
                "items": [],
                "without_case": self.metrics(4, 2, 1),
            },
        )

    def test_participants_are_registered_team_users_deduplicated_per_bucket(self):
        field = create_case_field(self.program)
        leader, collaborator, outsider, invited, profile_only = [
            create_user(password=None) for _ in range(5)
        ]
        for user in (leader, collaborator, invited, profile_only):
            create_program_member(self.program, user=user)
        create_program_member(create_partner_program(), user=outsider)
        first = self.link(field, "A", project=create_project(leader=leader))
        second = self.link(field, "A", project=create_project(leader=leader))
        third = self.link(field, "B", project=create_project(leader=leader))
        without = self.link(project=create_project(leader=leader))
        for project in (first.project, second.project):
            Collaborator.objects.create(project=project, user=collaborator)
        Collaborator.objects.bulk_create(
            [Collaborator(project=first.project, user=outsider)]
        )
        Collaborator.objects.filter(project=second.project, user=leader).delete()
        Invite.objects.create(project=first.project, user=invited)
        PartnerProgramUserProfile.objects.filter(
            partner_program=self.program, user=profile_only
        ).update(project=first.project)
        cases = self.overview()["cases"]
        self.assertEqual(cases["items"][0], {"name": "A", **self.metrics(2, 0, 2)})
        self.assertEqual(cases["items"][1], {"name": "B", **self.metrics(1, 0, 1)})
        self.assertEqual(cases["without_case"], self.metrics(1, 0, 1))
        self.assertTrue(third.pk and without.pk)

    def test_one_registered_user_can_count_once_in_multiple_case_buckets(self):
        field = create_case_field(self.program)
        user = create_user(password=None)
        create_program_member(self.program, user=user)
        for value in ("A", "A", "B", None, "old", ""):
            self.link(field, value, project=create_project(leader=user))
        cases = self.overview()["cases"]
        self.assertEqual(
            [item["participants_total"] for item in cases["items"]], [1, 1, 0]
        )
        self.assertEqual(cases["without_case"], self.metrics(3, 0, 1))
        self.assertEqual(self.overview()["summary"]["participants"]["total"], 1)

    def test_noncompetitive_keeps_raw_case_and_funnel_counts(self):
        PartnerProgram.objects.filter(pk=self.program.pk).update(is_competitive=False)
        self.program.is_competitive = False
        field = create_case_field(self.program)
        self.link(
            field,
            "A",
            submitted=True,
            project=create_project(draft=True, is_public=False),
        )
        draft = self.link(
            field,
            "A",
            project=create_project(draft=False, is_public=True),
        )
        PartnerProgramProject.objects.filter(pk=draft.pk).update(
            datetime_submitted=self.program.datetime_started
        )
        overview = self.overview()
        self.assertFalse(overview["cases"]["submission_applicable"])
        self.assertEqual(
            overview["cases"]["items"][0], {"name": "A", **self.metrics(2, 1)}
        )
        self.assertEqual(overview["solution_funnel"]["not_submitted"], 1)
        self.assertEqual(
            overview["attention"]["projects_not_submitted"],
            {"applicable": False, "total": 0},
        )

    def test_same_project_in_two_programs_has_independent_values_and_submitted_state(
        self,
    ):
        field_a = create_case_field(self.program, options=["A", "B"])
        other = create_partner_program(is_competitive=True)
        other.managers.add(self.manager)
        field_b = create_case_field(other, options=["A", "B"])
        user = create_user(password=None)
        for program in (self.program, other):
            create_program_member(program, user=user)
        shared = create_project(leader=user)
        self.link(field_a, "A", project=shared, submitted=True)
        self.link(field_b, "B", program=other, project=shared, submitted=False)
        case_a, case_b = self.overview()["cases"], self.overview(other)["cases"]
        self.assertEqual(case_a["items"][0], {"name": "A", **self.metrics(1, 1, 1)})
        self.assertEqual(case_a["items"][1], {"name": "B", **self.metrics(0, 0)})
        self.assertEqual(case_b["items"][0], {"name": "A", **self.metrics(0, 0)})
        self.assertEqual(case_b["items"][1], {"name": "B", **self.metrics(1, 0, 1)})

    def test_case_service_is_exactly_four_queries_for_one_and_twenty_options(self):
        field = create_case_field(self.program, options=["A"])
        user = create_user(password=None)
        create_program_member(self.program, user=user)
        self.link(field, "A", project=create_project(leader=user))
        counts = []
        for options in (["A"], ["A", *[f"Case {index}" for index in range(19)]]):
            PartnerProgramField.objects.filter(pk=field.pk).update(
                options="|".join(options)
            )
            with CaptureQueriesContext(connection) as queries:
                cases = build_project_case_analytics(self.program)
            counts.append(len(queries))
            self.assertEqual(len(cases["items"]), len(options))
        self.assertEqual(counts, [4, 4])

    def test_case_and_root_serializers_are_sql_free_and_reject_negative_counts(self):
        create_case_field(self.program)
        payload = self.overview()
        with self.assertNumQueries(0):
            root = ProjectAnalyticsSerializer(data=payload)
            self.assertTrue(root.is_valid(), root.errors)
            self.assertEqual(root.data, payload)
        for bucket_index, bucket in enumerate(
            [*payload["cases"]["items"], payload["cases"]["without_case"]]
        ):
            for metric in self.metrics(0, 0):
                invalid = deepcopy(payload["cases"])
                target = (
                    invalid["items"][bucket_index]
                    if bucket_index < len(invalid["items"])
                    else invalid["without_case"]
                )
                target[metric] = -1
                with self.subTest(
                    bucket=bucket_index, metric=metric
                ), self.assertNumQueries(0):
                    self.assertFalse(
                        ProjectCaseAnalyticsSerializer(data=invalid).is_valid()
                    )


class ProjectAnalyticsCrossDomainTests(ProjectCaseAnalyticsFixture, TestCase):
    def attention_urls(self):
        return [
            reverse(
                f"partner_programs:project-analytics-{suffix}",
                kwargs={"program_id": self.program.pk},
            )
            for suffix in (
                "participants-without-team",
                "projects-awaiting-evaluation",
                "projects-not-submitted",
            )
        ]

    def create_production_domain(self):
        user = create_user(password=None)
        expert_user = create_rate_expert(program=self.program)
        application = Application.objects.create(
            program=self.program,
            user=user,
            created_by=user,
            participation_mode=Application.PARTICIPATION_MODE_TEAM,
        )
        team = Team.objects.create(application=application, captain=user)
        TeamMember.objects.create(
            team=team,
            user=user,
            role=TeamMember.ROLE_CAPTAIN,
            status=TeamMember.STATUS_ACCEPTED,
        )
        submission = Submission.objects.create(
            application=application,
            program=self.program,
            submitted_by=user,
            title="Production only",
            status=Submission.STATUS_SUBMITTED,
        )
        assignment = SubmissionExpertAssignment.objects.create(
            submission=submission,
            expert=expert_user.expert,
            assigned_by=self.manager,
        )
        evaluation = Evaluation.objects.create(
            submission=submission, expert=expert_user.expert
        )
        return expert_user, assignment, evaluation

    def test_production_entities_do_not_change_attention_lists_or_cases(self):
        before_lists = [self.client.get(url).content for url in self.attention_urls()]
        before_cases = self.overview()["cases"]
        self.create_production_domain()
        self.assertEqual(
            [self.client.get(url).content for url in self.attention_urls()],
            before_lists,
        )
        self.assertEqual(self.overview()["cases"], before_cases)

    def test_legacy_entities_do_not_change_production_apis(self):
        expert_user, assignment, evaluation = self.create_production_domain()
        urls = [
            reverse(
                "partner_programs:manager-overview",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:submission-assignment-list-create",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:evaluation-list",
                kwargs={"program_id": self.program.pk},
            ),
            reverse(
                "partner_programs:evaluation-detail",
                kwargs={
                    "program_id": self.program.pk,
                    "evaluation_id": evaluation.pk,
                },
            ),
        ]
        before = [self.client.get(url).content for url in urls]
        field = create_case_field(self.program)
        link = self.link(field, "A", submitted=True)
        legacy_assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program,
            project=link.project,
            expert=expert_user.expert,
        )
        criterion = self.program.criterias.order_by("pk").first()
        ProjectScore.objects.create(
            project=link.project,
            user=expert_user,
            criteria=criterion,
            value="legacy",
        )
        self.assertEqual([self.client.get(url).content for url in urls], before)
        self.assertTrue(legacy_assignment.pk and assignment.pk)

    def test_legacy_services_never_query_production_domain_tables(self):
        self.create_production_domain()
        with CaptureQueriesContext(connection) as queries:
            build_project_case_analytics(self.program)
            for url in self.attention_urls():
                self.client.get(url)
        for model in (
            Application,
            Team,
            TeamMember,
            Submission,
            SubmissionExpertAssignment,
            Evaluation,
        ):
            for query in queries:
                self.assertNotIn(f'"{model._meta.db_table}"', query["sql"])

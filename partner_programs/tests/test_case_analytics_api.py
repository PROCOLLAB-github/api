"""Case analytics reconciles links and deduplicates registered team participants."""

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from invites.models import Invite
from partner_programs.models import (
    PartnerProgramField,
    PartnerProgramFieldValue,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.serializers.analytics import (
    ProgramCaseAnalyticsSerializer,
    ProgramManagerAnalyticsSerializer,
)
from partner_programs.services.analytics import build_program_manager_analytics
from partner_programs.services.case_analytics import build_case_analytics
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.tests.test_case_fields import create_case_field
from projects.models import Collaborator


class ProgramCaseAnalyticsTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(is_competitive=True)
        self.manager = create_user()
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def overview(self, program=None):
        response = self.client.get(
            reverse(
                "partner_programs:manager-overview",
                kwargs={"pk": (program or self.program).pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assert_reconciled(response.data)
        return response.data

    def assert_reconciled(self, overview):
        cases = overview["cases"]
        buckets = [*cases["items"], cases["without_case"]]
        for bucket in buckets:
            self.assertEqual(
                bucket["projects_total"], bucket["not_submitted"] + bucket["submitted"]
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

    def link(self, field=None, value=None, *, submitted=False, project=None):
        link = create_program_project(self.program, project=project)
        if field is not None and value is not None:
            # Bypass write guards only to seed historical/corrupted analytics data.
            PartnerProgramFieldValue.objects.bulk_create(
                [
                    PartnerProgramFieldValue(
                        program_project=link, field=field, value_text=value
                    )
                ]
            )
        PartnerProgramProject.objects.filter(pk=link.pk).update(submitted=submitted)
        return link

    def test_basic_counts_options_order_zero_row_and_funnel_reconciliation(self):
        field = create_case_field(self.program, options=["Case A", "Case B", "Case C"])
        self.link(field, "Case A", submitted=True)
        self.link(field, "Case A")
        self.link(field, "Case B", submitted=True)
        self.link()
        self.link(field, "Legacy")
        cases = self.overview()["cases"]
        self.assertTrue(cases["configured"])
        self.assertTrue(cases["submission_applicable"])
        self.assertEqual(
            cases["items"],
            [
                dict(name="Case A", **self.metrics(2, 1)),
                dict(name="Case B", **self.metrics(1, 1)),
                dict(name="Case C", **self.metrics(0, 0)),
            ],
        )
        self.assertEqual(cases["without_case"], self.metrics(2, 0))

    @staticmethod
    def metrics(projects, submitted, participants=0):
        return {
            "participants_total": participants,
            "projects_total": projects,
            "not_submitted": projects - submitted,
            "submitted": submitted,
        }

    def test_membership_is_unique_within_case_and_registered_in_this_program(self):
        field = create_case_field(self.program)
        leader, second, third, outsider, invited, profile_only = [
            create_user() for _ in range(6)
        ]
        for user in (leader, second, third, invited, profile_only):
            create_program_member(self.program, user=user)
        create_program_member(create_partner_program(), user=outsider)
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program, user=None, partner_program_data={}
        )
        first = self.link(field, "A", project=create_project(leader=leader))
        second_link = self.link(field, "A", project=create_project(leader=leader))
        for project, user in (
            (first.project, leader),
            (first.project, second),
            (second_link.project, second),
            (second_link.project, third),
        ):
            Collaborator.objects.get_or_create(project=project, user=user)
        # Only bypass validation to represent a pre-existing outsider membership.
        Collaborator.objects.bulk_create(
            [Collaborator(project=first.project, user=outsider)]
        )
        # The leader must count even without the collaborator row added by signals.
        Collaborator.objects.filter(project=second_link.project, user=leader).delete()
        Invite.objects.create(project=first.project, user=invited)
        PartnerProgramUserProfile.objects.filter(
            partner_program=self.program, user=profile_only
        ).update(project=first.project)
        overview = self.overview()
        self.assertEqual(
            overview["cases"]["items"][0], dict(name="A", **self.metrics(2, 0, 3))
        )
        self.assertEqual(overview["summary"]["participants"]["total"], 5)

    def test_profile_uniqueness_is_enforced_and_does_not_inflate_participants(self):
        field = create_case_field(self.program)
        user = create_user()
        create_program_member(self.program, user=user)
        self.link(field, "A", project=create_project(leader=user))
        # Current schema forbids the legacy duplicate-profile fixture.
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_program_member(self.program, user=user)
        self.assertEqual(self.overview()["cases"]["items"][0]["participants_total"], 1)

    def test_participant_can_count_once_in_each_case_and_without_case(self):
        field = create_case_field(self.program)
        user = create_user()
        create_program_member(self.program, user=user)
        for value in ("A", "A", "B", None, "old", ""):
            self.link(field, value, project=create_project(leader=user))
        overview = self.overview()
        self.assertEqual(overview["summary"]["participants"]["total"], 1)
        cases = overview["cases"]
        self.assertEqual(
            [item["participants_total"] for item in cases["items"]], [1, 1, 0]
        )
        self.assertEqual(cases["without_case"], self.metrics(3, 0, 1))

    def test_missing_empty_whitespace_obsolete_and_nonexact_values_are_without_case(self):
        field = create_case_field(self.program)
        for index, value in enumerate((None, "", "  ", "Legacy", "a", " A ")):
            self.link(field, value, submitted=index % 2 == 0)
        cases = self.overview()["cases"]
        self.assertEqual(cases["without_case"], self.metrics(6, 3))
        self.assertTrue(all(item["projects_total"] == 0 for item in cases["items"]))

    def test_other_program_definition_and_values_cannot_classify_a_link(self):
        field = create_case_field(self.program)
        other = create_partner_program(is_competitive=True)
        other.managers.add(self.manager)
        other_field = create_case_field(other)
        shared = create_project()
        # Same project has separate A/B program links, choices and submitted flags.
        first = self.link(field, "A", project=shared, submitted=True)
        second = create_program_project(other, project=shared)
        PartnerProgramFieldValue.objects.create(
            program_project=second, field=other_field, value_text="B"
        )
        self.link(
            other_field, "B"
        )  # Corrupted value pointing at another program's field.
        cases = self.overview()["cases"]
        self.assertEqual(cases["items"][0]["projects_total"], 1)
        self.assertEqual(cases["items"][1]["projects_total"], 0)
        self.assertEqual(cases["without_case"]["projects_total"], 1)
        other_cases = self.overview(other)["cases"]
        self.assertEqual(other_cases["items"][1], dict(name="B", **self.metrics(1, 0)))
        self.assertNotEqual(first.pk, second.pk)

    def test_lookalike_system_names_are_not_recognised(self):
        for name in ("case_name", "cases", "Case", "кейс"):
            with self.subTest(name=name):
                program = create_partner_program()
                field = create_program_field(
                    program,
                    name=name,
                    label="Кейс",
                    field_type="select",
                    options=["A"],
                    show_filter=True,
                )
                link = create_program_project(program)
                PartnerProgramFieldValue.objects.create(
                    program_project=link, field=field, value_text="A"
                )
                cases = build_case_analytics(program)
                self.assertFalse(cases["configured"])
                self.assertEqual(cases["items"], [])
                self.assertEqual(cases["without_case"], self.metrics(1, 0))

    def test_exact_system_name_is_authoritative_even_for_legacy_definition_flags(self):
        field = create_case_field(self.program, label="Unrelated label")
        self.link(field, "A")
        PartnerProgramField.objects.filter(pk=field.pk).update(
            field_type="text", is_required=False, show_filter=False
        )
        cases = self.overview()["cases"]
        self.assertTrue(cases["configured"])
        self.assertEqual(cases["items"][0]["projects_total"], 1)

    def test_absent_definition_places_all_links_and_participants_without_case(self):
        user = create_user()
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

    def test_zero_projects_keeps_all_options_in_configuration_order(self):
        field = create_case_field(self.program, options=["C", "A", "B"])
        cases = self.overview()["cases"]
        self.assertEqual(
            cases["items"],
            [dict(name=name, **self.metrics(0, 0)) for name in ("C", "A", "B")],
        )
        self.assertEqual(cases["without_case"], self.metrics(0, 0))
        self.link(field, "A")
        self.link(field, "A")
        populated = self.overview()["cases"]["items"]
        self.assertEqual([item["name"] for item in populated], ["C", "A", "B"])
        self.assertEqual([item["projects_total"] for item in populated], [0, 2, 0])

    def test_noncompetitive_counts_raw_submitted_flag_not_project_or_timestamp(self):
        self.program.is_competitive = False
        self.program.save()
        field = create_case_field(self.program)
        self.link(
            field,
            "A",
            submitted=True,
            project=create_project(draft=True, is_public=False),
        )
        unsent = self.link(
            field, "A", project=create_project(draft=False, is_public=True)
        )
        PartnerProgramProject.objects.filter(pk=unsent.pk).update(
            datetime_submitted=self.program.datetime_started
        )
        cases = self.overview()["cases"]
        self.assertTrue(cases["configured"])
        self.assertFalse(cases["submission_applicable"])
        self.assertEqual(cases["items"][0], dict(name="A", **self.metrics(2, 1)))

    def test_fixed_four_query_budget_at_one_and_twenty_options(self):
        field = create_case_field(self.program, options=["A"])
        user = create_user()
        create_program_member(self.program, user=user)
        for _ in range(2):
            link = self.link(field, "A", project=create_project(leader=user))
            Collaborator.objects.get_or_create(project=link.project, user=user)
        counts = []
        for options in (["A"], ["A", *[f"Case {index}" for index in range(19)]]):
            field.options = "|".join(options)
            field.save()
            with self.assertNumQueries(4):
                cases = build_case_analytics(self.program)
            self.assertEqual(len(cases["items"]), len(options))
            with CaptureQueriesContext(connection) as queries:
                self.overview()
            counts.append(len(queries))
        self.assertEqual(counts[0], counts[1])
        self.assertLessEqual(counts[1], 14)

    def test_serializers_preserve_contract_without_sql_and_reject_negative_metrics(self):
        create_case_field(self.program)
        overview = build_program_manager_analytics(self.program)
        with self.assertNumQueries(0):
            serializer = ProgramManagerAnalyticsSerializer(data=overview)
            self.assertTrue(serializer.is_valid(), serializer.errors)
            self.assertEqual(serializer.data["cases"], overview["cases"])
        for bucket in (overview["cases"]["items"][0], overview["cases"]["without_case"]):
            for metric in self.metrics(0, 0):
                with self.subTest(bucket=bucket, metric=metric):
                    bucket[metric] = -1
                    serializer = ProgramCaseAnalyticsSerializer(data=overview["cases"])
                    self.assertFalse(serializer.is_valid())
                    bucket[metric] = 0

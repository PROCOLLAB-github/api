"""Link-scoped field contract, legacy compatibility, isolation and bounded reads."""

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from invites.models import Invite
from partner_programs.models import PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.tests.test_case_fields import create_case_field
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator


class ProgramLinkFieldsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.leader = create_user()
        self.client.force_authenticate(self.leader)
        self.program = create_partner_program(is_competitive=True)
        self.other_program = create_partner_program(is_competitive=True)
        self.project = create_project(leader=self.leader, draft=True, is_public=False)
        self.link = create_program_project(self.program, project=self.project)
        self.other_link = create_program_project(self.other_program, project=self.project)
        self.field = create_case_field(self.program)
        self.other_field = create_case_field(self.other_program, options=["Other"])
        self.url = f"/programs/partner-program-projects/{self.link.pk}/fields/"
        self.legacy_url = f"/projects/{self.project.pk}/program-fields/"

    def put(self, items, url=None):
        return self.client.put(url or self.url, items, format="json")

    def test_get_context_order_null_value_and_other_program_isolation(self):
        extra = create_program_field(self.program)
        PartnerProgramFieldValue.objects.create(
            program_project=self.other_link, field=self.other_field, value_text="Other"
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {key: value for key, value in response.data.items() if key != "fields"},
            {
                "program_link_id": self.link.pk,
                "program_id": self.program.pk,
                "project_id": self.project.pk,
                "submitted": False,
            },
        )
        fields = response.data["fields"]
        self.assertEqual([item["id"] for item in fields], [self.field.pk, extra.pk])
        self.assertIsNone(fields[0]["value"])
        self.assertEqual(fields[0]["options"], ["A", "B", "C"])
        self.assertEqual(
            set(fields[0]),
            {
                "id",
                "name",
                "label",
                "field_type",
                "is_required",
                "show_filter",
                "help_text",
                "options",
                "value",
            },
        )

    def test_partial_update_changes_only_requested_link(self):
        extra = create_program_field(self.program)
        self.put([{"field_id": extra.pk, "value_text": "preserve"}])
        other_url = f"/programs/partner-program-projects/{self.other_link.pk}/fields/"
        self.assertEqual(
            self.put(
                [{"field_id": self.other_field.pk, "value_text": "Other"}], other_url
            ).status_code,
            200,
        )
        for value in ("A", "B"):
            self.assertEqual(
                self.put([{"field_id": self.field.pk, "value_text": value}]).status_code,
                200,
            )
        self.assertEqual(self.link.field_values.get(field=extra).value_text, "preserve")
        self.assertEqual(self.link.field_values.get(field=self.field).value_text, "B")
        self.assertEqual(self.other_link.field_values.get().value_text, "Other")
        self.assertEqual(self.client.get(self.url).data["fields"][0]["value"], "B")

    def test_cannot_use_other_program_field_even_when_same_project(self):
        response = self.put([{"field_id": self.other_field.pk, "value_text": "invalid"}])
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Other", str(response.data))
        self.assertFalse(PartnerProgramFieldValue.objects.exists())

    def test_duplicate_ids_are_rejected_without_writes(self):
        response = self.put(
            [{"field_id": self.field.pk, "value_text": value} for value in ("A", "B")]
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.link.field_values.exists())

    def test_invalid_second_item_leaves_first_value_unchanged(self):
        extra = create_program_field(self.program)
        self.put([{"field_id": extra.pk, "value_text": "before"}])
        response = self.put(
            [
                {"field_id": extra.pk, "value_text": "after"},
                {"field_id": self.field.pk, "value_text": "missing"},
            ]
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.link.field_values.get(field=extra).value_text, "before")
        self.assertFalse(self.link.field_values.filter(field=self.field).exists())

    def test_case_cannot_be_explicitly_empty(self):
        for value in (None, "", " ", "missing"):
            with self.subTest(value=value):
                self.assertEqual(
                    self.put(
                        [{"field_id": self.field.pk, "value_text": value}]
                    ).status_code,
                    400,
                )
        self.assertFalse(self.link.field_values.exists())

    def test_model_validation_error_rolls_back_an_earlier_write(self):
        extra = create_program_field(self.program)
        original_save = PartnerProgramFieldValue.save

        def save(value, *args, **kwargs):
            if value.field_id == self.field.pk:
                raise ValidationError("Конфигурация кейса изменилась.")
            return original_save(value, *args, **kwargs)

        with patch.object(PartnerProgramFieldValue, "save", save):
            response = self.put(
                [
                    {"field_id": extra.pk, "value_text": "must roll back"},
                    {"field_id": self.field.pk, "value_text": "A"},
                ]
            )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.link.field_values.exists())

    def test_submitted_competitive_link_blocks_all_field_updates(self):
        extra = create_program_field(self.program)
        self.link.submitted = True
        self.link.save()
        for field, value in ((self.field, "B"), (extra, "text")):
            self.assertEqual(
                self.put([{"field_id": field.pk, "value_text": value}]).status_code, 400
            )
        self.assertFalse(self.link.field_values.exists())

    def test_get_allows_existing_project_involvement_and_current_program_roles(self):
        manager = create_user()
        self.program.managers.add(manager)
        expert = create_rate_expert(program=self.program)
        teammate = create_user()
        create_program_member(self.program, user=teammate)
        create_program_member(self.other_program, user=teammate)
        Collaborator.objects.create(user=teammate, project=self.project)
        invited = create_user()
        Invite.objects.create(user=invited, project=self.project)
        for user in (
            self.leader,
            manager,
            expert,
            teammate,
            invited,
            create_user(is_staff=True),
            create_user(is_superuser=True),
        ):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_program_roles_are_scoped_to_requested_link_after_production_732(self):
        manager = create_user()
        self.program.managers.add(manager)
        expert = create_rate_expert(program=self.program)
        other_url = f"/programs/partner-program-projects/{self.other_link.pk}/fields/"
        for user in (manager, expert):
            self.client.force_authenticate(user)
            with self.subTest(user=user.pk):
                allowed = self.client.get(self.url)
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(allowed.data["program_link_id"], self.link.pk)
                self.assertEqual(self.client.get(other_url).status_code, 403)

    def test_independent_project_roles_can_read_both_links(self):
        teammate = create_user()
        create_program_member(self.program, user=teammate)
        create_program_member(self.other_program, user=teammate)
        Collaborator.objects.create(user=teammate, project=self.project)
        invited = create_user()
        Invite.objects.create(user=invited, project=self.project)
        for user in (
            self.leader,
            teammate,
            invited,
            create_user(is_staff=True),
            create_user(is_superuser=True),
        ):
            self.program.managers.add(user)
            self.client.force_authenticate(user)
            for link in (self.link, self.other_link):
                with self.subTest(user=user.pk, link=link.pk):
                    response = self.client.get(
                        f"/programs/partner-program-projects/{link.pk}/fields/"
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.data["program_link_id"], link.pk)

    def test_get_does_not_leak_private_fields_to_outsider_or_other_program_roles(self):
        manager = create_user()
        self.other_program.managers.add(manager)
        for user in (
            create_user(),
            manager,
            create_rate_expert(program=self.other_program),
        ):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_public_project_alone_does_not_expose_program_fields(self):
        self.project.draft = False
        self.project.is_public = True
        self.project.save()
        self.client.force_authenticate(create_user())
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_put_is_leader_only_without_manager_expert_or_staff_override(self):
        manager = create_user()
        self.program.managers.add(manager)
        for user in (
            create_user(),
            manager,
            create_rate_expert(program=self.program),
            create_user(is_staff=True),
            create_user(is_superuser=True),
        ):
            self.client.force_authenticate(user)
            self.assertEqual(
                self.put([{"field_id": self.field.pk, "value_text": "A"}]).status_code,
                403,
            )
        self.assertFalse(self.link.field_values.exists())

    def test_authentication_missing_link_and_unsupported_method(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.put([]).status_code, 401)
        self.client.force_authenticate(self.leader)
        self.assertEqual(
            self.client.get(
                "/programs/partner-program-projects/999999/fields/"
            ).status_code,
            404,
        )
        self.assertEqual(self.client.post(self.url, [], format="json").status_code, 405)

    def test_legacy_multiple_links_returns_409_without_selecting_first(self):
        response = self.put(
            [{"field_id": self.field.pk, "value_text": "A"}], self.legacy_url
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["detail"].code, "ambiguous_program_link")
        self.assertFalse(PartnerProgramFieldValue.objects.exists())

    def test_legacy_single_link_still_works(self):
        self.other_link.delete()
        self.assertEqual(
            self.put(
                [{"field_id": self.field.pk, "value_text": "A"}], self.legacy_url
            ).status_code,
            200,
        )
        self.assertEqual(self.link.field_values.get().value_text, "A")

    def test_legacy_no_links_returns_controlled_error(self):
        self.other_link.delete()
        self.link.delete()
        self.assertEqual(self.put([], self.legacy_url).status_code, 400)

    def get_query_counts(self, users, expected_fields):
        counts = []
        for user in users:
            self.client.force_authenticate(user)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data["fields"]), expected_fields)
            counts.append(len(queries))
        return counts

    def test_get_has_constant_queries_for_one_or_twenty_fields(self):
        manager = create_user()
        self.program.managers.add(manager)
        expert = create_rate_expert(program=self.program)
        users = (self.leader, manager, expert)
        single = self.get_query_counts(users, 1)
        for _ in range(19):
            field = create_program_field(self.program)
            PartnerProgramFieldValue.objects.create(
                program_project=self.link, field=field, value_text="text"
            )
        self.assertEqual(self.get_query_counts(users, 20), single)

"""Link-scoped field contract, legacy compatibility, isolation and bounded reads."""

from unittest.mock import patch

from django.core.exceptions import ValidationError

from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgram, PartnerProgramFieldValue
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
                "is_competitive": True,
                "submission_open": True,
                "submission_deadline": self.program.datetime_registration_ends,
                "can_submit": True,
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

    def assert_submission_metadata(
        self, link, *, competitive, submission_open, deadline, can_submit
    ):
        response = self.client.get(
            f"/programs/partner-program-projects/{link.pk}/fields/"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["program_link_id"], link.pk)
        self.assertEqual(data["program_id"], link.partner_program_id)
        self.assertIs(data["is_competitive"], competitive)
        self.assertIs(data["submission_open"], submission_open)
        self.assertIs(data["can_submit"], can_submit)
        if deadline is None:
            self.assertIsNone(data["submission_deadline"])
        else:
            self.assertEqual(parse_datetime(data["submission_deadline"]), deadline)

    def test_competitive_open_metadata_uses_submission_deadline(self):
        deadline = timezone.now() + timezone.timedelta(days=2)
        self.program.datetime_project_submission_ends = deadline
        self.program.save(update_fields=["datetime_project_submission_ends"])
        self.assert_submission_metadata(
            self.link,
            competitive=True,
            submission_open=True,
            deadline=deadline,
            can_submit=True,
        )

    def test_competitive_closed_metadata(self):
        deadline = timezone.now() - timezone.timedelta(days=1)
        self.program.datetime_project_submission_ends = deadline
        self.program.save(update_fields=["datetime_project_submission_ends"])
        self.assert_submission_metadata(
            self.link,
            competitive=True,
            submission_open=False,
            deadline=deadline,
            can_submit=False,
        )

    def test_already_submitted_metadata_keeps_window_open_but_cannot_submit(self):
        self.link.submitted = True
        self.link.save(update_fields=["submitted"])
        self.assert_submission_metadata(
            self.link,
            competitive=True,
            submission_open=True,
            deadline=self.program.datetime_registration_ends,
            can_submit=False,
        )

    def test_noncompetitive_metadata_keeps_window_open_but_cannot_submit(self):
        self.program.is_competitive = False
        self.program.save(update_fields=["is_competitive"])
        self.assert_submission_metadata(
            self.link,
            competitive=False,
            submission_open=True,
            deadline=self.program.datetime_registration_ends,
            can_submit=False,
        )

    def test_metadata_preserves_nullable_deadline_from_program_method(self):
        # Current records require a registration deadline; preserve the helper contract
        # without changing the schema to manufacture an otherwise impossible record.
        with patch.object(
            PartnerProgram, "get_project_submission_deadline", return_value=None
        ):
            self.assert_submission_metadata(
                self.link,
                competitive=True,
                submission_open=True,
                deadline=None,
                can_submit=True,
            )

    def test_metadata_uses_requested_link_when_project_has_different_program_states(self):
        closed_deadline = timezone.now() - timezone.timedelta(days=1)
        self.program.datetime_project_submission_ends = closed_deadline
        self.program.save(update_fields=["datetime_project_submission_ends"])
        self.link.submitted = True
        self.link.save(update_fields=["submitted"])
        # B is deliberately not the first link, and must not inherit A's closed/submitted state.
        self.assert_submission_metadata(
            self.other_link,
            competitive=True,
            submission_open=True,
            deadline=self.other_program.datetime_registration_ends,
            can_submit=True,
        )
        self.assert_submission_metadata(
            self.link,
            competitive=True,
            submission_open=False,
            deadline=closed_deadline,
            can_submit=False,
        )
        self.other_program.is_competitive = False
        self.other_program.save(update_fields=["is_competitive"])
        self.assert_submission_metadata(
            self.other_link,
            competitive=False,
            submission_open=True,
            deadline=self.other_program.datetime_registration_ends,
            can_submit=False,
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
        for user in (
            self.leader,
            manager,
            expert,
            teammate,
            create_user(is_staff=True),
            create_user(is_superuser=True),
        ):
            with self.subTest(user=user.pk):
                self.client.force_authenticate(user)
                self.assertEqual(self.client.get(self.url).status_code, 200)

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
            create_user(is_staff=True, is_superuser=True),
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
        self.assertEqual(
            self.put(
                [{"field_id": self.field.pk, "value_text": "A"}], self.legacy_url
            ).status_code,
            409,
        )
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

    def test_get_uses_three_queries_for_one_or_twenty_fields(self):
        with self.assertNumQueries(3):
            first = self.client.get(self.url)
        self.assertEqual(len(first.data["fields"]), 1)
        self.assertIs(first.data["can_submit"], True)
        for _ in range(19):
            field = create_program_field(self.program)
            PartnerProgramFieldValue.objects.create(
                program_project=self.link, field=field, value_text="text"
            )
        with self.assertNumQueries(3):
            many = self.client.get(self.url)
        self.assertEqual(len(many.data["fields"]), 20)
        self.assertIs(many.data["can_submit"], True)

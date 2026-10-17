from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.db import connections
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.urls import reverse
from rest_framework.test import APIClient

from partner_programs.models import PartnerProgramField, PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_project,
    create_program_member,
    create_user,
)


class ManagementProjectFormTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(is_competitive=True)
        self.manager = create_user()
        self.program.managers.add(self.manager)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = reverse(
            "partner_programs:management-project-form", kwargs={"pk": self.program.pk}
        )

    def payload(self):
        snapshot = self.client.get(self.url).data
        keys = ("id", "label", "field_type", "is_required", "help_text", "options")
        return {
            "expected_updated_at": snapshot["updated_at"],
            "expected_revision": snapshot["revision"],
            "cases": [c["name"] for c in snapshot["cases"]],
            "fields": [{k: f[k] for k in keys} for f in snapshot["fields"]],
        }

    def put(self, data):
        return self.client.put(self.url, data, format="json")

    def field(self, **overrides):
        return {
            "label": "Ссылка на прототип",
            "field_type": "text",
            "is_required": False,
            "help_text": "Откройте доступ",
            "options": [],
            **overrides,
        }

    def test_configuration_roundtrip_and_legacy_names(self):
        old = create_program_field(self.program, name="legacy-prototype")
        data = self.payload()
        data["cases"] = ["Кейс А", "Кейс Б"]
        data["fields"].append(self.field(field_type="select", options=["А", "Б"]))
        response = self.put(data)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["cases"][0], {"name": "Кейс А", "projects_count": 0}
        )
        self.assertNotEqual(response.data["revision"], data["expected_revision"])
        old.refresh_from_db()
        self.assertEqual(old.name, "legacy-prototype")
        self.assertEqual(len(response.data["fields"]), 2)
        self.assertTrue(self.program.fields.get(name="case").is_required)

    def test_scope_and_auth_apply_to_reads_and_writes(self):
        data = self.payload()
        for user, status in [
            (create_user(), 403),
            (None, 401),
            (create_user(is_staff=True), 200),
        ]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, status)
            self.assertEqual(self.put(data).status_code, status)

    def test_stale_program_and_admin_definition_edits_rejected(self):
        field = create_program_field(self.program)
        data = self.payload()
        field.label = "Changed in admin"
        field.save()
        self.assertEqual(self.put(data).status_code, 409)
        fresh = self.payload()
        self.program.name = "Changed basics"
        self.program.save()
        self.assertEqual(self.put(fresh).status_code, 409)
        self.assertEqual(self.program.fields.get(pk=field.pk).label, "Changed in admin")

    def test_invalid_case_rolls_back_other_changes(self):
        data = self.payload()
        data["cases"] = ["Same", " same "]
        data["fields"] = [self.field()]
        self.assertEqual(self.put(data).status_code, 400)
        self.assertFalse(self.program.fields.exists())

    def test_foreign_and_duplicate_fields_rejected(self):
        foreign = create_program_field(create_partner_program())
        for ids in ([foreign.pk], [foreign.pk, foreign.pk]):
            data = self.payload()
            data["fields"] = [self.field(id=pk) for pk in ids]
            self.assertEqual(self.put(data).status_code, 400)
        self.assertFalse(self.program.fields.exists())

    def test_used_case_and_field_guards_preserve_answers(self):
        case = create_program_field(
            self.program,
            name="case",
            field_type="select",
            is_required=True,
            show_filter=True,
            options=["A", "B"],
        )
        field = create_program_field(
            self.program, field_type="select", options=["One", "Two"]
        )
        link = create_program_project(self.program)
        for definition, value in [(case, "A"), (field, "One")]:
            PartnerProgramFieldValue.objects.create(
                field=definition, program_project=link, value_text=value
            )
        snapshot = self.client.get(self.url).data
        self.assertEqual(snapshot["cases"][0]["projects_count"], 1)
        self.assertEqual(snapshot["fields"][0]["answers_count"], 1)
        for change in ("case", "delete", "type", "choice"):
            data = self.payload()
            if change == "case":
                data["cases"] = ["B"]
            if change == "delete":
                data["fields"] = []
            if change == "type":
                data["fields"][0].update(field_type="text", options=[])
            if change == "choice":
                data["fields"][0]["options"] = ["Two"]
            self.assertEqual(self.put(data).status_code, 400, change)
        self.assertEqual(
            PartnerProgramFieldValue.objects.filter(program_project=link).count(), 2
        )

    def test_unused_case_and_field_can_be_removed(self):
        create_program_field(
            self.program,
            name="case",
            field_type="select",
            is_required=True,
            show_filter=True,
            options=["A"],
        )
        create_program_field(self.program)
        data = self.payload()
        data.update(cases=[], fields=[])
        self.assertEqual(self.put(data).status_code, 200)
        self.assertFalse(self.program.fields.exists())

    def test_existing_checkbox_can_be_preserved_but_not_created(self):
        old = create_program_field(self.program, field_type="checkbox", is_required=True)
        data = self.payload()
        data["fields"][0]["label"] = "Новое название"
        self.assertEqual(self.put(data).status_code, 200)
        old.refresh_from_db()
        self.assertEqual(old.label, "Новое название")
        data = self.payload()
        data["fields"].append(self.field(field_type="checkbox"))
        self.assertEqual(self.put(data).status_code, 400)

    def test_rejects_unknown_properties_and_invalid_choices(self):
        for item in (
            self.field(unknown="value"),
            self.field(field_type="select", options=[]),
            self.field(field_type="select", options=["A|B"]),
            self.field(options=["unexpected"]),
        ):
            data = self.payload()
            data["fields"] = [item]
            self.assertEqual(self.put(data).status_code, 400)
        self.assertEqual(
            PartnerProgramField.objects.filter(partner_program=self.program).count(), 0
        )

    def test_new_required_fields_apply_only_to_unsubmitted_projects(self):
        frozen = create_program_project(self.program, submitted=True)
        draft = create_program_project(self.program)
        create_program_member(self.program, user=frozen.project.leader)
        create_program_member(self.program, user=draft.project.leader)
        data = self.payload()
        data["fields"] = [self.field(is_required=True)]
        response = self.put(data)
        self.assertEqual(response.status_code, 200, response.data)
        frozen.refresh_from_db()
        self.assertTrue(frozen.submitted)
        self.assertFalse(frozen.field_values.exists())
        self.client.force_authenticate(frozen.project.leader)
        self.assertEqual(
            self.client.put(
                f"/programs/partner-program-projects/{frozen.pk}/fields/",
                [{"field_id": response.data["fields"][0]["id"], "value_text": "change"}],
                format="json",
            ).status_code,
            400,
        )
        self.client.force_authenticate(draft.project.leader)
        self.assertEqual(
            self.client.post(
                f"/programs/partner-program-projects/{draft.pk}/submit/"
            ).status_code,
            400,
        )
        draft.refresh_from_db()
        self.assertFalse(draft.submitted)

    def test_empty_draft_value_does_not_lock_unused_field(self):
        field = create_program_field(self.program)
        link = create_program_project(self.program)
        # Historical apply used bulk_create and could leave an empty value row.
        PartnerProgramFieldValue.objects.bulk_create(
            [PartnerProgramFieldValue(field=field, program_project=link, value_text="")]
        )
        self.assertEqual(self.client.get(self.url).data["fields"][0]["answers_count"], 0)
        data = self.payload()
        data["fields"] = []
        self.assertEqual(self.put(data).status_code, 200)
        self.assertFalse(self.program.fields.exists())

    def test_late_used_case_error_rolls_back_new_field(self):
        case = create_program_field(
            self.program,
            name="case",
            field_type="select",
            is_required=True,
            show_filter=True,
            options=["A", "B"],
        )
        link = create_program_project(self.program)
        PartnerProgramFieldValue.objects.create(
            field=case, program_project=link, value_text="A"
        )
        data = self.payload()
        data["cases"] = ["B"]
        data["fields"] = [self.field()]
        self.assertEqual(self.put(data).status_code, 400)
        self.assertEqual(self.program.fields.count(), 1)
        self.assertEqual(link.field_values.get().value_text, "A")


@skipUnlessDBFeature("has_select_for_update")
class ManagementProjectFormLockTests(TransactionTestCase):
    def test_concurrent_manager_saves_have_one_winner(self):
        from partner_programs.services.management_form import (
            form_data,
            save_form,
            StaleProjectForm,
        )

        program = create_partner_program()
        manager = create_user()
        program.managers.add(manager)
        snapshot = form_data(program)
        barrier = Barrier(2)

        def save(name):
            try:
                barrier.wait(timeout=10)
                save_form(
                    program.pk,
                    manager,
                    {
                        "expected_updated_at": snapshot["updated_at"],
                        "expected_revision": snapshot["revision"],
                        "cases": [name],
                        "fields": [],
                    },
                )
                return 200
            except StaleProjectForm:
                return 409
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ["A", "B"]))
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(program.fields.count(), 1)

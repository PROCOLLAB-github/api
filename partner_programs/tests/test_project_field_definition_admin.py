from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from partner_programs.models import PartnerProgramField, PartnerProgramFieldValue
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_project,
    create_user,
)


class ProjectFieldDefinitionAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(
            create_user(is_staff=True, is_superuser=True, is_active=True)
        )
        self.program = create_partner_program(
            draft=True, data_schema={"name": {"name": "Имя"}}
        )
        self.link = create_program_project(self.program)

    def field_with_answer(self, field_type):
        field = create_program_field(
            self.program, field_type=field_type, options=["А", "Б"]
        )
        value = PartnerProgramFieldValue.objects.create(
            field=field, program_project=self.link, value_text="А"
        )
        return field, value

    def field_payload(self, field):
        return {
            "partner_program": self.program.pk,
            "name": field.name,
            "label": field.label,
            "field_type": field.field_type,
            "purpose": field.purpose,
            "position": field.position,
            "validation": "{}",
            "options": field.options,
        }

    def assert_answer_survives(self, field, value, field_type, options):
        field.refresh_from_db()
        value.refresh_from_db()
        self.assertEqual(field.field_type, field_type)
        self.assertEqual(field.get_options_list(), options)
        self.assertEqual(value.value_text, "А")
        self.assertEqual(value.field_id, field.pk)
        self.assertEqual(value.program_project_id, self.link.pk)

    def test_standalone_radio_field_preserves_answer_and_allows_unused_option_changes(
        self,
    ):
        field, value = self.field_with_answer("radio")
        url = reverse(
            "admin:partner_programs_partnerprogramfield_change", args=[field.pk]
        )
        payload = self.field_payload(field)
        for changes, error_key in (
            ({"field_type": "text", "options": ""}, "field_type"),
            ({"options": "Переименованный А|Б"}, "options"),
            ({"solution_options": '["Б"]'}, "options"),
        ):
            with self.subTest(changes=changes):
                response = self.client.post(url, {**payload, **changes})
                self.assertEqual(response.status_code, 200)
                errors = response.context["adminform"].form.errors
                self.assertIn("ответ", errors[error_key][0])
                self.assert_answer_survives(field, value, "radio", ["А", "Б"])
        response = self.client.post(url, {**payload, "options": "А|В"})
        self.assertEqual(response.status_code, 302)
        self.assert_answer_survives(field, value, "radio", ["А", "В"])

    def test_program_inline_select_field_preserves_answer_and_allows_reordering(self):
        field, value = self.field_with_answer("select")
        url = reverse(
            "admin:partner_programs_partnerprogram_change", args=[self.program.pk]
        )
        payload = {
            "name": self.program.name,
            "tag": self.program.tag,
            "description": self.program.description,
            "city": self.program.city,
            "draft": "on",
            "projects_availability": self.program.projects_availability,
            "data_schema": '{"name": {"name": "Имя"}}',
            "project_sections": "{}",
        }
        for name in (
            "datetime_started",
            "datetime_finished",
            "datetime_registration_ends",
        ):
            date = timezone.localtime(getattr(self.program, name))
            payload[f"{name}_0"] = date.strftime("%Y-%m-%d")
            payload[f"{name}_1"] = date.strftime("%H:%M:%S")
        page = self.client.get(url)
        for inline in page.context["inline_admin_formsets"]:
            formset = inline.formset
            prefix = formset.prefix
            if formset.model is PartnerProgramField:
                row = f"{prefix}-0"
                payload[f"{prefix}-TOTAL_FORMS"] = 1
                payload[f"{prefix}-INITIAL_FORMS"] = 1
                payload[f"{row}-id"] = field.pk
                payload.update(
                    {f"{row}-{key}": val for key, val in self.field_payload(field).items()}
                )
            else:
                payload[f"{prefix}-TOTAL_FORMS"] = 0
                payload[f"{prefix}-INITIAL_FORMS"] = 0

        for changes, error in (
            (
                {f"{row}-field_type": "text", f"{row}-options": ""},
                "Нельзя изменить тип поля с ответами.",
            ),
            (
                {f"{row}-options": "Б"},
                "Нельзя удалить или переименовать использованный вариант ответа.",
            ),
        ):
            with self.subTest(changes=changes):
                self.assertContains(self.client.post(url, {**payload, **changes}), error)
                self.assert_answer_survives(field, value, "select", ["А", "Б"])
        response = self.client.post(url, {**payload, f"{row}-options": "Б|А"})
        self.assertEqual(response.status_code, 302)
        self.assert_answer_survives(field, value, "select", ["Б", "А"])

    def test_unanswered_field_type_can_still_change(self):
        field = create_program_field(self.program, field_type="select", options=["А"])
        url = reverse(
            "admin:partner_programs_partnerprogramfield_change", args=[field.pk]
        )
        payload = self.field_payload(field)
        payload.update(field_type="text", options="")
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        field.refresh_from_db()
        self.assertEqual(field.field_type, "text")

    def test_unanswered_field_can_still_move_to_another_program(self):
        field = create_program_field(self.program)
        other = create_partner_program()
        url = reverse(
            "admin:partner_programs_partnerprogramfield_change", args=[field.pk]
        )
        self.assertEqual(self.client.get(url).status_code, 200)
        field.refresh_from_db()
        self.assertEqual(field.partner_program_id, self.program.pk)
        response = self.client.post(
            url, {**self.field_payload(field), "partner_program": other.pk}
        )
        self.assertEqual(response.status_code, 302)
        field.refresh_from_db()
        self.assertEqual(field.partner_program_id, other.pk)

    def test_field_with_saved_value_cannot_move_to_another_program(self):
        other = create_partner_program()
        for text in ("Сохраненный ответ", ""):
            with self.subTest(value=text):
                field = create_program_field(self.program)
                value = PartnerProgramFieldValue(
                    program_project=self.link, field=field, value_text=text
                )
                PartnerProgramFieldValue.objects.bulk_create([value])
                url = reverse(
                    "admin:partner_programs_partnerprogramfield_change", args=[field.pk]
                )
                response = self.client.post(
                    url, {**self.field_payload(field), "partner_program": other.pk}
                )
                self.assertContains(
                    response, "Нельзя переносить поле с ответами в другую программу."
                )
                field.refresh_from_db()
                value.refresh_from_db()
                self.assertEqual(field.partner_program_id, self.program.pk)
                self.assertEqual(value.program_project_id, self.link.pk)
                self.assertEqual(value.field_id, field.pk)
                self.assertEqual(value.value_text, text)

    def test_missing_field_is_not_created_by_change_post(self):
        field = create_program_field(self.program)
        url = reverse(
            "admin:partner_programs_partnerprogramfield_change", args=[field.pk]
        )
        payload = self.field_payload(field)
        field.delete()
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertFalse(self.program.fields.exists())

    def test_add_post_creates_field_in_selected_program(self):
        field = PartnerProgramField(
            partner_program=self.program, name="new_field", label="Новое поле",
            field_type="text",
        )
        payload = self.field_payload(field)
        payload["options"] = ""
        url = reverse("admin:partner_programs_partnerprogramfield_add")
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.program.fields.filter(name=field.name).exists())

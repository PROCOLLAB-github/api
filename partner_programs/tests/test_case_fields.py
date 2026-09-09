"""Reserved definition rules, history preservation and standard admin validation."""

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms import inlineformset_factory, modelform_factory
from django.test import RequestFactory, TestCase

from partner_programs.admin import PartnerProgramFieldAdmin
from partner_programs.forms import ProgramFieldInlineFormSet
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramFieldValue,
)
from partner_programs.services.case_fields import is_program_case_field
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_project,
    create_user,
)


def create_case_field(program, **overrides):
    """Create a real definition; no auto-generated case in generic test programs."""
    values = dict(
        name="case",
        label="Выберите задачу",
        field_type="select",
        is_required=True,
        show_filter=True,
        options=["A", "B", "C"],
    )
    values.update(overrides)
    return create_program_field(program, **values)


class ProgramCaseConfigurationTests(TestCase):
    def setUp(self):
        self.program = create_partner_program()

    def test_valid_case_with_custom_label_and_trimmed_options(self):
        field = create_case_field(self.program, options=[" A ", "B"])
        self.assertTrue(is_program_case_field(field))
        self.assertEqual(field.get_options_list(), ["A", "B"])
        self.assertEqual(field.label, "Выберите задачу")

    def test_only_exact_name_is_reserved_and_generic_fields_are_unchanged(self):
        for name in ("Кейс", "case_name", "track", "Case", "CASE"):
            with self.subTest(name=name):
                field = create_program_field(self.program, name=name, label="Кейс")
                field.full_clean()
                self.assertFalse(is_program_case_field(field))

    def test_non_select_case_types_are_rejected(self):
        for kind in ("text", "textarea", "checkbox", "radio", "file"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError) as error:
                create_case_field(self.program, field_type=kind)
            self.assertIn("field_type", error.exception.message_dict)

    def test_required_and_filter_flags_cannot_be_disabled(self):
        for flag in ("is_required", "show_filter"):
            with self.subTest(flag=flag), self.assertRaises(ValidationError) as error:
                create_case_field(self.program, **{flag: False})
            self.assertIn(flag, error.exception.message_dict)

    def test_empty_and_duplicate_options_are_rejected(self):
        for options in ([], [""], ["A", ""], [" ", "A"], ["A", "A"], ["AI", " ai "]):
            with self.subTest(options=options), self.assertRaises(
                ValidationError
            ) as error:
                create_case_field(self.program, options=options)
            self.assertIn("options", error.exception.message_dict)

    def test_database_still_prevents_second_reserved_name(self):
        field = create_case_field(self.program)
        duplicate = PartnerProgramField(
            partner_program=self.program,
            name=field.name,
            label="Duplicate",
            field_type="select",
            is_required=True,
            show_filter=True,
            options="A",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerProgramField.objects.bulk_create([duplicate])

    def test_program_has_no_automatic_case(self):
        self.assertFalse(self.program.fields.exists())


class ProgramCaseHistoryTests(TestCase):
    def setUp(self):
        self.program = create_partner_program(is_competitive=True)
        self.field = create_case_field(self.program)
        self.link = create_program_project(self.program)
        self.value = PartnerProgramFieldValue.objects.create(
            program_project=self.link, field=self.field, value_text="B"
        )

    def test_add_option_and_remove_unused_option(self):
        for options in ("A|B|C|D", "B|C"):
            self.field.options = options
            self.field.save()
        self.value.refresh_from_db()
        self.assertEqual(self.value.value_text, "B")

    def test_remove_or_rename_used_option_is_rejected_on_save(self):
        for options in ("A|C", "A|B renamed|C", "A|b|C"):
            self.field.options = options
            with self.subTest(options=options), self.assertRaises(ValidationError):
                self.field.save()
            self.field.refresh_from_db()
            self.assertEqual(self.field.options, "A|B|C")

    def test_label_and_help_text_can_change_without_changing_values(self):
        self.field.label = "Новая подпись"
        self.field.help_text = "Пояснение"
        self.field.save()
        self.value.refresh_from_db()
        self.assertEqual(self.value.value_text, "B")

    def test_used_case_name_and_program_cannot_change(self):
        self.field.name = "track"
        with self.assertRaises(ValidationError):
            self.field.save()
        self.field.refresh_from_db()
        self.field.partner_program = create_partner_program()
        with self.assertRaises(ValidationError):
            self.field.save()

    def test_generic_option_edit_retains_existing_behavior(self):
        field = create_program_field(
            self.program, name="track", field_type="select", options=["A"]
        )
        PartnerProgramFieldValue.objects.create(
            program_project=self.link, field=field, value_text="A"
        )
        field.options = "B"
        field.full_clean()
        field.save()

    def test_direct_case_value_save_validates_choice_and_program(self):
        self.value.value_text = "unknown"
        with self.assertRaises(ValidationError):
            self.value.save()
        other = create_program_project(create_partner_program())
        with self.assertRaises(ValidationError):
            PartnerProgramFieldValue.objects.create(
                program_project=other, field=self.field, value_text="A"
            )

    def test_stale_link_instance_cannot_edit_case_after_submission(self):
        type(self.link).objects.filter(pk=self.link.pk).update(submitted=True)
        self.value.value_text = "C"
        with self.assertRaises(ValidationError):
            self.value.save()
        self.value.refresh_from_db()
        self.assertEqual(self.value.value_text, "B")

    def test_admin_modelform_uses_config_and_history_rules(self):
        form_class = modelform_factory(PartnerProgramField, fields="__all__")
        data = dict(
            partner_program=self.program.pk,
            name="case",
            label="Case",
            field_type="select",
            is_required=True,
            show_filter=True,
            options="A|C",
        )
        form = form_class(data=data, instance=self.field)
        self.assertFalse(form.is_valid())
        self.assertIn("options", form.errors)
        data.update(options="A|B|C", field_type="text")
        self.assertIn("field_type", form_class(data=data, instance=self.field).errors)

    def test_inline_cannot_delete_used_case_but_can_delete_unused_generic_field(self):
        factory = inlineformset_factory(
            PartnerProgram,
            PartnerProgramField,
            formset=ProgramFieldInlineFormSet,
            fields="__all__",
            can_delete=True,
        )

        def formset_for(field):
            return factory(
                instance=self.program,
                prefix="fields",
                data={
                    "fields-TOTAL_FORMS": "1",
                    "fields-INITIAL_FORMS": "1",
                    "fields-0-id": field.pk,
                    "fields-0-partner_program": self.program.pk,
                    "fields-0-name": field.name,
                    "fields-0-label": field.label,
                    "fields-0-field_type": field.field_type,
                    "fields-0-is_required": True,
                    "fields-0-show_filter": True,
                    "fields-0-options": field.options,
                    "fields-0-DELETE": True,
                },
            )

        used = formset_for(self.field)
        self.assertFalse(used.is_valid())
        self.assertIn("Нельзя удалить", str(used.non_form_errors()))
        unused = create_program_field(self.program)
        self.assertTrue(formset_for(unused).is_valid())

    def test_standard_admin_delete_confirmation_protects_used_case(self):
        request = RequestFactory().get("/admin/")
        request.user = create_user(is_staff=True, is_superuser=True)
        model_admin = PartnerProgramFieldAdmin(PartnerProgramField, admin.site)
        protected = model_admin.get_deleted_objects([self.field], request)[3]
        self.assertTrue(protected)
        unused = create_case_field(create_partner_program())
        self.assertFalse(model_admin.get_deleted_objects([unused], request)[3])

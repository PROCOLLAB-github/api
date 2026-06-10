from django.test import TestCase

from partner_programs.serializers import PartnerProgramFieldValueUpdateSerializer
from partner_programs.tests.helpers import create_partner_program, create_program_field


class PartnerProgramFieldValueUpdateSerializerInvalidTests(TestCase):
    def setUp(self):
        self.partner_program = create_partner_program(draft=True)

    def make_field(self, field_type, is_required, options=None):
        return create_program_field(
            self.partner_program,
            field_type=field_type,
            is_required=is_required,
            options=options,
        )

    def test_required_text_field_empty(self):
        field = self.make_field("text", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": ""}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Поле должно содержать текстовое значение.", str(serializer.errors)
        )

    def test_required_textarea_field_null(self):
        field = self.make_field("textarea", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": None}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Поле должно содержать текстовое значение.", str(serializer.errors)
        )

    def test_checkbox_invalid_string(self):
        field = self.make_field("checkbox", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "maybe"}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("ожидается 'true' или 'false'", str(serializer.errors).lower())

    def test_checkbox_invalid_type(self):
        field = self.make_field("checkbox", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": 1}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("ожидается 'true' или 'false'", str(serializer.errors).lower())

    def test_select_invalid_choice(self):
        field = self.make_field("select", is_required=True, options=["арбуз", "ананас"])
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "яблоко"}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Недопустимое значение для поля типа 'select'", str(serializer.errors)
        )

    def test_select_required_empty(self):
        field = self.make_field("select", is_required=True, options=["арбуз", "ананас"])
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": ""}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Значение обязательно для поля типа 'select'", str(serializer.errors)
        )

    def test_radio_invalid_type(self):
        field = self.make_field("radio", is_required=True, options=["арбуз", "ананас"])
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": ["арбуз"]}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("Not a valid string.", str(serializer.errors))

    def test_radio_invalid_value(self):
        field = self.make_field("radio", is_required=True, options=["арбуз", "ананас"])
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "груша"}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Недопустимое значение для поля типа 'radio'", str(serializer.errors)
        )

    def test_file_invalid_type(self):
        field = self.make_field("file", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": 123}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Ожидается корректная ссылка (URL) на файл.", str(serializer.errors)
        )

    def test_file_empty_required(self):
        field = self.make_field("file", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": ""}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("Файл обязателен для этого поля.", str(serializer.errors))


class PartnerProgramFieldValueUpdateSerializerValidTests(TestCase):
    def setUp(self):
        self.partner_program = create_partner_program(draft=True)

    def make_field(self, field_type, is_required, options=None):
        return create_program_field(
            self.partner_program,
            field_type=field_type,
            is_required=is_required,
            options=options,
        )

    def test_optional_text_field_valid(self):
        field = self.make_field("text", is_required=False)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "some value"}
        )

        self.assertTrue(serializer.is_valid())

    def test_required_text_field_valid(self):
        field = self.make_field("text", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "not empty"}
        )

        self.assertTrue(serializer.is_valid())

    def test_optional_textarea_valid(self):
        field = self.make_field("textarea", is_required=False)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "optional long text"}
        )

        self.assertTrue(serializer.is_valid())

    def test_required_textarea_valid(self):
        field = self.make_field("textarea", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "required long text"}
        )

        self.assertTrue(serializer.is_valid())

    def test_checkbox_true_valid(self):
        field = self.make_field("checkbox", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "true"}
        )

        self.assertTrue(serializer.is_valid())

    def test_checkbox_false_valid(self):
        field = self.make_field("checkbox", is_required=False)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "false"}
        )

        self.assertTrue(serializer.is_valid())

    def test_select_valid(self):
        field = self.make_field("select", is_required=True, options=["арбуз", "ананас"])
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "ананас"}
        )

        self.assertTrue(serializer.is_valid())

    def test_radio_valid(self):
        field = self.make_field(
            "radio", is_required=True, options=["арбуз", "апельсин"]
        )
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "апельсин"}
        )

        self.assertTrue(serializer.is_valid())

    def test_optional_select_empty_valid(self):
        field = self.make_field(
            "select", is_required=False, options=["арбуз", "апельсин"]
        )
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": ""}
        )

        self.assertTrue(serializer.is_valid())

    def test_file_valid_url(self):
        field = self.make_field("file", is_required=True)
        serializer = PartnerProgramFieldValueUpdateSerializer(
            data={"field_id": field.id, "value_text": "https://example.com/file.pdf"}
        )

        self.assertTrue(serializer.is_valid())

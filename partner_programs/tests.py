from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.serializers import PartnerProgramFieldValueUpdateSerializer
from partner_programs.services import publish_finished_program_projects
from projects.models import Project


class PartnerProgramFieldValueUpdateSerializerInvalidTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.partner_program = PartnerProgram.objects.create(
            name="Тестовая программа",
            tag="test_tag",
            description="Описание тестовой программы",
            city="Москва",
            image_address="https://example.com/image.png",
            cover_image_address="https://example.com/cover.png",
            advertisement_image_address="https://example.com/advertisement.png",
            presentation_address="https://example.com/presentation.pdf",
            data_schema={},
            draft=True,
            projects_availability="all_users",
            datetime_registration_ends=now + timezone.timedelta(days=30),
            datetime_started=now,
            datetime_finished=now + timezone.timedelta(days=60),
        )

    def make_field(self, field_type, is_required, options=None):
        return PartnerProgramField.objects.create(
            partner_program=self.partner_program,
            name="test_field",
            label="Test Field",
            field_type=field_type,
            is_required=is_required,
            options="|".join(options) if options else "",
        )

    def test_required_text_field_empty(self):
        field = self.make_field("text", is_required=True)
        data = {"field_id": field.id, "value_text": ""}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Поле должно содержать текстовое значение.", str(serializer.errors)
        )

    def test_required_textarea_field_null(self):
        field = self.make_field("textarea", is_required=True)
        data = {"field_id": field.id, "value_text": None}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Поле должно содержать текстовое значение.", str(serializer.errors)
        )

    def test_checkbox_invalid_string(self):
        field = self.make_field("checkbox", is_required=True)
        data = {"field_id": field.id, "value_text": "maybe"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("ожидается 'true' или 'false'", str(serializer.errors).lower())

    def test_checkbox_invalid_type(self):
        field = self.make_field("checkbox", is_required=True)
        data = {"field_id": field.id, "value_text": 1}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("ожидается 'true' или 'false'", str(serializer.errors).lower())

    def test_select_invalid_choice(self):
        field = self.make_field("select", is_required=True, options=["арбуз", "ананас"])
        data = {"field_id": field.id, "value_text": "яблоко"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Недопустимое значение для поля типа 'select'", str(serializer.errors)
        )

    def test_select_required_empty(self):
        field = self.make_field("select", is_required=True, options=["арбуз", "ананас"])
        data = {"field_id": field.id, "value_text": ""}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Значение обязательно для поля типа 'select'", str(serializer.errors)
        )

    def test_radio_invalid_type(self):
        field = self.make_field("radio", is_required=True, options=["арбуз", "ананас"])
        data = {"field_id": field.id, "value_text": ["арбуз"]}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("Not a valid string.", str(serializer.errors))

    def test_radio_invalid_value(self):
        field = self.make_field("radio", is_required=True, options=["арбуз", "ананас"])
        data = {"field_id": field.id, "value_text": "груша"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Недопустимое значение для поля типа 'radio'", str(serializer.errors)
        )

    def test_file_invalid_type(self):
        field = self.make_field("file", is_required=True)
        data = {"field_id": field.id, "value_text": 123}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Ожидается корректная ссылка (URL) на файл.", str(serializer.errors)
        )

    def test_file_empty_required(self):
        field = self.make_field("file", is_required=True)
        data = {"field_id": field.id, "value_text": ""}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("Файл обязателен для этого поля.", str(serializer.errors))


class PublishFinishedProgramProjectsTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user(
            email="user@example.com",
            password="pass",
            first_name="User",
            last_name="Test",
            birthday="1990-01-01",
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Program",
            "tag": "program_tag",
            "description": "Program description",
            "city": "Moscow",
            "image_address": "https://example.com/image.png",
            "cover_image_address": "https://example.com/cover.png",
            "advertisement_image_address": "https://example.com/advertisement.png",
            "presentation_address": "https://example.com/presentation.pdf",
            "data_schema": {},
            "draft": False,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now - timezone.timedelta(days=5),
            "datetime_started": self.now - timezone.timedelta(days=30),
            "datetime_finished": self.now - timezone.timedelta(days=1),
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def create_project(self, **overrides):
        defaults = {
            "leader": self.user,
            "draft": False,
            "is_public": False,
            "name": "Project",
        }
        defaults.update(overrides)
        return Project.objects.create(**defaults)

    def test_publish_updates_projects_from_both_sources(self):
        program = self.create_program(publish_projects_after_finish=True)

        link_project = self.create_project(name="Linked Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=link_project,
        )

        profile_project = self.create_project(name="Profile Project")
        PartnerProgramUserProfile.objects.create(
            user=self.user,
            partner_program=program,
            project=profile_project,
            partner_program_data={},
        )

        publish_finished_program_projects()

        link_project.refresh_from_db()
        profile_project.refresh_from_db()
        self.assertTrue(link_project.is_public)
        self.assertTrue(profile_project.is_public)

    def test_publish_skips_draft_projects(self):
        program = self.create_program(publish_projects_after_finish=True)
        draft_project = self.create_project(draft=True, name="Draft Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=draft_project,
        )

        publish_finished_program_projects()

        draft_project.refresh_from_db()
        self.assertFalse(draft_project.is_public)

    def test_publish_skips_when_flag_false(self):
        program = self.create_program(publish_projects_after_finish=False)
        project = self.create_project(name="Private Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )

        publish_finished_program_projects()

        project.refresh_from_db()
        self.assertFalse(project.is_public)

    def test_publish_after_flag_enabled_post_finish(self):
        program = self.create_program(publish_projects_after_finish=False)
        project = self.create_project(name="Delayed Project")
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )

        publish_finished_program_projects()
        project.refresh_from_db()
        self.assertFalse(project.is_public)

        program.publish_projects_after_finish = True
        program.save(update_fields=["publish_projects_after_finish"])

        publish_finished_program_projects()
        project.refresh_from_db()
        self.assertTrue(project.is_public)


class PartnerProgramFieldValueUpdateSerializerValidTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.partner_program = PartnerProgram.objects.create(
            name="Тестовая программа",
            tag="test_tag",
            description="Описание тестовой программы",
            city="Москва",
            image_address="https://example.com/image.png",
            cover_image_address="https://example.com/cover.png",
            advertisement_image_address="https://example.com/advertisement.png",
            presentation_address="https://example.com/presentation.pdf",
            data_schema={},
            draft=True,
            projects_availability="all_users",
            datetime_registration_ends=now + timezone.timedelta(days=30),
            datetime_started=now,
            datetime_finished=now + timezone.timedelta(days=60),
        )

    def make_field(self, field_type, is_required, options=None):
        return PartnerProgramField.objects.create(
            partner_program=self.partner_program,
            name="test_field",
            label="Test Field",
            field_type=field_type,
            is_required=is_required,
            options="|".join(options) if options else "",
        )

    def test_optional_text_field_valid(self):
        field = self.make_field("text", is_required=False)
        data = {"field_id": field.id, "value_text": "some value"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_required_text_field_valid(self):
        field = self.make_field("text", is_required=True)
        data = {"field_id": field.id, "value_text": "not empty"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_optional_textarea_valid(self):
        field = self.make_field("textarea", is_required=False)
        data = {"field_id": field.id, "value_text": "optional long text"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_required_textarea_valid(self):
        field = self.make_field("textarea", is_required=True)
        data = {"field_id": field.id, "value_text": "required long text"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_checkbox_true_valid(self):
        field = self.make_field("checkbox", is_required=True)
        data = {"field_id": field.id, "value_text": "true"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_checkbox_false_valid(self):
        field = self.make_field("checkbox", is_required=False)
        data = {"field_id": field.id, "value_text": "false"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_select_valid(self):
        field = self.make_field("select", is_required=True, options=["арбуз", "ананас"])
        data = {"field_id": field.id, "value_text": "ананас"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_radio_valid(self):
        field = self.make_field(
            "radio", is_required=True, options=["арбуз", "апельсин"]
        )
        data = {"field_id": field.id, "value_text": "апельсин"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_optional_select_empty_valid(self):
        field = self.make_field(
            "select", is_required=False, options=["арбуз", "апельсин"]
        )
        data = {"field_id": field.id, "value_text": ""}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_file_valid_url(self):
        field = self.make_field("file", is_required=True)
        data = {"field_id": field.id, "value_text": "https://example.com/file.pdf"}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

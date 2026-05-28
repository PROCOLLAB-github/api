from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from unittest.mock import patch

from courses.models import Course, CourseAccessType, CourseContentStatus
from partner_programs.constants import get_default_data_schema
from partner_programs.models import (
    LegalDocument,
    PartnerProgram,
    PartnerProgramField,
    PartnerProgramLegalSettings,
    PartnerProgramParticipantConsent,
    PartnerProgramProject,
    PartnerProgramUserProfile,
)
from partner_programs.serializers import PartnerProgramFieldValueUpdateSerializer
from partner_programs.services import publish_finished_program_projects
from partner_programs.tasks import send_readiness_reminders
from partner_programs.views import (
    ActiveLegalDocumentsView,
    PartnerProgramDetail,
    PartnerProgramList,
    PartnerProgramProjectApplyView,
    PartnerProgramRegister,
    PartnerProgramProjectSubmitView,
    PartnerProgramReadinessView,
    PartnerProgramSubmitToModerationView,
)
from projects.models import Company, Project
from users.models import UserNotificationPreferences


class PartnerProgramPrivacyLegalTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.client = APIClient()
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user(
            email="participant@example.com",
            password="pass",
            first_name="Participant",
            last_name="Test",
            birthday="1990-01-01",
        )
        self.manager = get_user_model().objects.create_user(
            email="manager-privacy@example.com",
            password="pass",
            first_name="Manager",
            last_name="Test",
            birthday="1990-01-01",
        )
        self.program = PartnerProgram.objects.create(
            name="Privacy Program",
            tag="privacy_program",
            description="Program description",
            city="Moscow",
            image_address="https://example.com/image.png",
            cover_image_address="https://example.com/cover.png",
            advertisement_image_address="https://example.com/advertisement.png",
            presentation_address="https://example.com/presentation.pdf",
            data_schema={},
            draft=False,
            status=PartnerProgram.STATUS_PUBLISHED,
            projects_availability="all_users",
            datetime_registration_ends=self.now + timezone.timedelta(days=30),
            datetime_started=self.now,
            datetime_finished=self.now + timezone.timedelta(days=60),
        )
        self.program.managers.add(self.manager)
        self.ensure_legal_documents()

    def ensure_legal_documents(self):
        documents = (
            ("privacy_policy", "Privacy policy"),
            ("participant_consent", "Participant consent"),
            ("participation_terms", "Participation terms"),
            ("organizer_terms", "Organizer terms"),
        )
        for doc_type, title in documents:
            LegalDocument.objects.update_or_create(
                type=doc_type,
                version="test",
                defaults={
                    "title": title,
                    "content_html": f"{title} text",
                    "is_active": True,
                },
            )

    def test_active_legal_documents_returns_latest_active_per_type(self):
        LegalDocument.objects.create(
            type="privacy_policy",
            title="Old privacy policy",
            version="old",
            content_html="old",
            is_active=True,
        )
        latest = LegalDocument.objects.create(
            type="privacy_policy",
            title="Latest privacy policy",
            version="latest",
            content_html="latest",
            is_active=True,
        )

        request = self.factory.get("/programs/legal-documents/active/")
        response = ActiveLegalDocumentsView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        docs_by_type = {item["type"]: item for item in response.data}
        self.assertEqual(docs_by_type["privacy_policy"]["id"], latest.id)
        self.assertIn("participant_consent", docs_by_type)
        self.assertIn("participation_terms", docs_by_type)
        self.assertIn("organizer_terms", docs_by_type)

    def test_manager_can_update_and_accept_program_legal_settings(self):
        self.client.force_authenticate(self.manager)

        settings_response = self.client.patch(
            f"/programs/{self.program.id}/legal-settings/",
            {
                "participation_rules_link": "https://example.com/rules.pdf",
                "additional_terms_text": "Extra terms",
            },
            format="json",
        )

        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(
            settings_response.data["participation_rules_link"],
            "https://example.com/rules.pdf",
        )
        self.assertEqual(settings_response.data["additional_terms_text"], "Extra terms")

        accept_response = self.client.post(
            f"/programs/{self.program.id}/legal-settings/accept-organizer-terms/",
            {},
            format="json",
        )

        self.assertEqual(accept_response.status_code, 200)
        self.assertEqual(accept_response.data["organizer_terms_version"], "test")
        settings = PartnerProgramLegalSettings.objects.get(program=self.program)
        self.assertEqual(settings.organizer_terms_accepted_by, self.manager)
        self.assertIsNotNone(settings.organizer_terms_accepted_at)

    def test_register_requires_personal_data_consent(self):
        request = self.factory.post(
            f"/programs/{self.program.id}/register/",
            {"education": "University"},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = PartnerProgramRegister.as_view()(request, pk=self.program.pk)

        self.assertEqual(response.status_code, 400)
        self.assertIn("personal_data_consent", response.data)
        self.assertFalse(
            PartnerProgramUserProfile.objects.filter(
                partner_program=self.program,
                user=self.user,
            ).exists()
        )
        self.assertFalse(
            PartnerProgramParticipantConsent.objects.filter(
                program=self.program,
                user=self.user,
            ).exists()
        )

    @patch("partner_programs.views.send_email.delay")
    def test_register_creates_consent_and_strips_consent_payload(self, send_email_delay):
        request = self.factory.post(
            f"/programs/{self.program.id}/register/",
            {
                "education": "University",
                "personalDataConsent": True,
            },
            format="json",
            HTTP_USER_AGENT="test-agent",
            REMOTE_ADDR="127.0.0.1",
        )
        force_authenticate(request, user=self.user)

        response = PartnerProgramRegister.as_view()(request, pk=self.program.pk)

        self.assertEqual(response.status_code, 201)
        profile = PartnerProgramUserProfile.objects.get(
            partner_program=self.program,
            user=self.user,
        )
        self.assertEqual(profile.partner_program_data, {"education": "University"})
        consent = PartnerProgramParticipantConsent.objects.get(
            program=self.program,
            user=self.user,
        )
        self.assertEqual(consent.consent_document_version, "test")
        self.assertEqual(consent.privacy_policy_version, "test")
        self.assertEqual(consent.participation_terms_version, "test")
        self.assertEqual(consent.ip_address, "127.0.0.1")
        self.assertEqual(consent.user_agent, "test-agent")
        send_email_delay.assert_called_once()

    def test_register_fails_when_required_legal_document_missing(self):
        LegalDocument.objects.filter(type="privacy_policy").update(is_active=False)
        request = self.factory.post(
            f"/programs/{self.program.id}/register/",
            {
                "education": "University",
                "personalDataConsent": True,
            },
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = PartnerProgramRegister.as_view()(request, pk=self.program.pk)

        self.assertEqual(response.status_code, 400)
        self.assertIn("missing_legal_documents", response.data)
        self.assertIn("privacy_policy", response.data["missing_legal_documents"])


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
        self.assertIn("Поле должно содержать текстовое значение.", str(serializer.errors))

    def test_required_textarea_field_null(self):
        field = self.make_field("textarea", is_required=True)
        data = {"field_id": field.id, "value_text": None}
        serializer = PartnerProgramFieldValueUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("Поле должно содержать текстовое значение.", str(serializer.errors))

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


class SendReadinessRemindersTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.manager = get_user_model().objects.create_user(
            email="manager-reminders@example.com",
            password="pass",
            first_name="Manager",
            last_name="Reminder",
            birthday="1990-01-01",
        )
        UserNotificationPreferences.objects.update_or_create(
            user=self.manager,
            defaults={"email_reminders_enabled": True},
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Reminder Program",
            "tag": "reminder_program",
            "description": "Program description " * 14,
            "city": "Moscow",
            "data_schema": {"fio": {"type": "text", "label": "FIO"}},
            "draft": False,
            "status": PartnerProgram.STATUS_PUBLISHED,
            "projects_availability": "all_users",
            "datetime_started": self.now + timezone.timedelta(days=7),
            "datetime_registration_ends": self.now + timezone.timedelta(days=3),
            "datetime_project_submission_ends": self.now + timezone.timedelta(days=5),
            "datetime_finished": self.now + timezone.timedelta(days=30),
            "sent_reminders": [],
        }
        defaults.update(overrides)
        program = PartnerProgram.objects.create(**defaults)
        program.managers.add(self.manager)
        return program

    @patch("partner_programs.tasks.send_mail", return_value=1)
    def test_readiness_reminder_is_idempotent(self, send_mail_mock):
        program = self.create_program()

        first_result = send_readiness_reminders()
        second_result = send_readiness_reminders()

        self.assertEqual(first_result, "Readiness reminders sent: 1")
        self.assertEqual(second_result, "Readiness reminders sent: 0")
        send_mail_mock.assert_called_once()
        program.refresh_from_db()
        self.assertEqual(program.sent_reminders, ["days_7"])


class PartnerProgramCoreListTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PartnerProgramList.as_view()
        self.now = timezone.now()

    def create_program(self, **overrides):
        defaults = {
            "name": "Core Program",
            "tag": "core_program",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "draft": False,
            "status": PartnerProgram.STATUS_PUBLISHED,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now - timezone.timedelta(days=1),
            "datetime_finished": self.now + timezone.timedelta(days=30),
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def test_list_returns_only_catalog_visible_programs(self):
        published_program = self.create_program(name="Published program")
        self.create_program(
            name="Draft program",
            draft=True,
            status=PartnerProgram.STATUS_DRAFT,
        )

        request = self.factory.get("/programs/")
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], published_program.id)

    def test_list_includes_company_summary(self):
        company = Company.objects.create(name="Organizer", inn="1234567890")
        program = self.create_program(company=company)

        request = self.factory.get("/programs/")
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        program_data = response.data["results"][0]
        self.assertEqual(program_data["id"], program.id)
        self.assertEqual(program_data["company_name"], "Organizer")
        self.assertEqual(
            program_data["company"],
            {"id": company.id, "name": "Organizer", "inn": "1234567890"},
        )


class PartnerProgramCreateUpdateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = timezone.now()
        self.manager = get_user_model().objects.create_user(
            email="manager-create-update@example.com",
            password="pass",
            first_name="Manager",
            last_name="User",
            birthday="1990-01-01",
        )
        self.outsider = get_user_model().objects.create_user(
            email="outsider-create-update@example.com",
            password="pass",
            first_name="Outsider",
            last_name="User",
            birthday="1990-01-01",
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Editable Case Championship",
            "tag": "editable_case_championship",
            "description": "Program description " * 14,
            "city": "Moscow",
            "data_schema": {"fio": {"type": "text", "label": "FIO"}},
            "draft": True,
            "status": PartnerProgram.STATUS_DRAFT,
            "projects_availability": "all_users",
            "datetime_started": self.now + timezone.timedelta(days=1),
            "datetime_registration_ends": self.now + timezone.timedelta(days=3),
            "datetime_project_submission_ends": self.now + timezone.timedelta(days=5),
            "datetime_finished": self.now + timezone.timedelta(days=10),
        }
        defaults.update(overrides)
        program = PartnerProgram.objects.create(**defaults)
        program.managers.add(self.manager)
        return program

    def payload(self, **overrides):
        data = {
            "name": "New Case Championship",
            "description": "Detailed program description " * 12,
            "city": "Moscow",
            "mobile_cover_image_address": "https://example.com/mobile-cover.png",
            "datetime_started": (self.now + timezone.timedelta(days=1)).isoformat(),
            "datetime_registration_ends": (
                self.now + timezone.timedelta(days=3)
            ).isoformat(),
            "datetime_project_submission_ends": (
                self.now + timezone.timedelta(days=5)
            ).isoformat(),
            "datetime_evaluation_ends": (
                self.now + timezone.timedelta(days=7)
            ).isoformat(),
            "datetime_finished": (self.now + timezone.timedelta(days=10)).isoformat(),
            "is_competitive": True,
            "participation_format": PartnerProgram.PARTICIPATION_FORMAT_TEAM,
            "project_team_min_size": 1,
            "project_team_max_size": 4,
        }
        data.update(overrides)
        return data

    def test_manager_can_create_draft_program_with_mobile_cover(self):
        self.client.force_authenticate(self.manager)

        response = self.client.post("/programs/", self.payload(), format="json")

        self.assertEqual(response.status_code, 201)
        program = PartnerProgram.objects.get(id=response.data["id"])
        self.assertEqual(program.status, PartnerProgram.STATUS_DRAFT)
        self.assertTrue(program.managers.filter(id=self.manager.id).exists())
        self.assertEqual(
            program.mobile_cover_image_address,
            "https://example.com/mobile-cover.png",
        )
        self.assertIsInstance(program.readiness, dict)

    def test_manager_can_update_draft_program(self):
        program = self.create_program()
        self.client.force_authenticate(self.manager)

        response = self.client.patch(
            f"/programs/{program.id}/",
            {
                "city": "Saint Petersburg",
                "mobile_cover_image_address": "https://example.com/new-mobile.png",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.city, "Saint Petersburg")
        self.assertEqual(
            program.mobile_cover_image_address,
            "https://example.com/new-mobile.png",
        )

    def test_outsider_cannot_update_program(self):
        program = self.create_program()
        self.client.force_authenticate(self.outsider)

        response = self.client.patch(
            f"/programs/{program.id}/",
            {"city": "Kazan"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_stats_endpoint_returns_program_counts(self):
        program = self.create_program(status=PartnerProgram.STATUS_PUBLISHED)
        user = get_user_model().objects.create_user(
            email="participant-stats@example.com",
            password="pass",
            first_name="Participant",
            last_name="Stats",
            birthday="1990-01-01",
        )
        PartnerProgramUserProfile.objects.create(
            partner_program=program,
            user=user,
            partner_program_data={},
        )
        project = Project.objects.create(
            leader=user,
            name="Stats Project",
            draft=False,
            is_public=False,
        )
        PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
            submitted=True,
            datetime_submitted=self.now,
        )

        response = self.client.get(f"/programs/{program.id}/stats/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["participants_count"], 1)
        self.assertEqual(response.data["projects_count"], 1)
        self.assertEqual(response.data["active_projects_count"], 1)


class PartnerProgramReadinessAndModerationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.readiness_view = PartnerProgramReadinessView.as_view()
        self.submit_view = PartnerProgramSubmitToModerationView.as_view()
        self.now = timezone.now()
        self.manager = get_user_model().objects.create_user(
            email="manager-readiness@example.com",
            password="pass",
            first_name="Manager",
            last_name="Readiness",
            birthday="1990-01-01",
        )
        self.ensure_legal_documents()

    def ensure_legal_documents(self):
        for doc_type, title in (
            ("privacy_policy", "Privacy policy"),
            ("participant_consent", "Participant consent"),
            ("participation_terms", "Participation terms"),
            ("organizer_terms", "Organizer terms"),
        ):
            LegalDocument.objects.update_or_create(
                type=doc_type,
                version="readiness-test",
                defaults={
                    "title": title,
                    "content_html": f"{title} text",
                    "is_active": True,
                },
            )

    def accept_legal_terms(self, program):
        PartnerProgramLegalSettings.objects.update_or_create(
            program=program,
            defaults={
                "organizer_terms_accepted_by": self.manager,
                "organizer_terms_accepted_at": self.now,
                "organizer_terms_version": "readiness-test",
            },
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Readiness Case Championship",
            "tag": f"readiness_case_{PartnerProgram.objects.count()}",
            "description": "Detailed championship description " * 12,
            "city": "Moscow",
            "data_schema": {
                "participant_name": {
                    "type": "text",
                    "label": "Participant name",
                }
            },
            "draft": True,
            "status": PartnerProgram.STATUS_DRAFT,
            "projects_availability": "all_users",
            "datetime_started": self.now + timezone.timedelta(days=1),
            "datetime_registration_ends": self.now + timezone.timedelta(days=3),
            "datetime_project_submission_ends": self.now + timezone.timedelta(days=5),
            "datetime_finished": self.now + timezone.timedelta(days=10),
        }
        defaults.update(overrides)
        program = PartnerProgram.objects.create(**defaults)
        program.managers.add(self.manager)
        return program

    def readiness(self, program):
        request = self.factory.get(f"/programs/{program.id}/readiness/")
        force_authenticate(request, user=self.manager)
        return self.readiness_view(request, pk=program.id)

    def submit(self, program):
        request = self.factory.post(
            f"/programs/{program.id}/submit-to-moderation/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.manager)
        return self.submit_view(request, pk=program.id)

    def test_new_draft_does_not_have_full_readiness(self):
        program = self.create_program(data_schema={})

        response = self.readiness(program)

        self.assertEqual(response.status_code, 200)
        self.assertLess(response.data["readiness_percent"], 100)
        self.assertFalse(response.data["can_submit_to_moderation"])
        self.assertIn("registration", response.data["missing_required_sections"])
        self.assertIn("legal_terms", response.data["missing_required_sections"])
        self.assertIn("sections", response.data)

    def test_each_required_section_blocks_submission_when_missing(self):
        cases = (
            (
                "basic_info",
                {"description": "too short"},
                True,
            ),
            (
                "dates",
                {"datetime_project_submission_ends": None},
                True,
            ),
            (
                "registration",
                {"data_schema": {}, "registration_link": ""},
                True,
            ),
            (
                "legal_terms",
                {},
                False,
            ),
        )

        for section, overrides, accept_terms in cases:
            with self.subTest(section=section):
                program = self.create_program(**overrides)
                if accept_terms:
                    self.accept_legal_terms(program)

                response = self.readiness(program)

                self.assertFalse(response.data["can_submit_to_moderation"])
                self.assertIn(section, response.data["missing_required_sections"])

    def test_optional_sections_lower_percent_but_do_not_block_moderation(self):
        program = self.create_program(is_competitive=True)
        self.accept_legal_terms(program)

        response = self.readiness(program)

        self.assertEqual(response.status_code, 200)
        self.assertLess(response.data["readiness_percent"], 100)
        self.assertTrue(response.data["can_submit_to_moderation"])
        self.assertNotIn("materials", response.data["missing_required_sections"])
        self.assertNotIn("criteria_experts", response.data["missing_required_sections"])
        self.assertNotIn("verification", response.data["missing_required_sections"])
        self.assertNotIn(
            "certificate_template",
            response.data["missing_required_sections"],
        )

    def test_default_registration_schema_is_not_ready_by_itself(self):
        program = self.create_program(data_schema=get_default_data_schema())
        self.accept_legal_terms(program)

        response = self.readiness(program)

        self.assertFalse(response.data["can_submit_to_moderation"])
        self.assertIn("registration", response.data["missing_required_sections"])

    def test_submit_to_moderation_returns_readiness_payload_when_incomplete(self):
        program = self.create_program(data_schema={})

        response = self.submit(program)

        self.assertEqual(response.status_code, 400)
        self.assertIn("missing_required_sections", response.data)
        self.assertIn("readiness_percent", response.data)
        self.assertIn("sections", response.data)
        self.assertIn("registration", response.data["missing_required_sections"])
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_DRAFT)

    @patch("moderation.services.notify_program_submitted_to_moderation", return_value=1)
    def test_submit_to_moderation_updates_status_only_when_required_ready(self, _notify):
        program = self.create_program()
        self.accept_legal_terms(program)

        response = self.submit(program)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_PENDING_MODERATION)

    @patch("moderation.services.notify_program_submitted_to_moderation", return_value=1)
    def test_rejected_program_can_be_resubmitted_after_fix(self, _notify):
        program = self.create_program(status=PartnerProgram.STATUS_REJECTED)
        self.accept_legal_terms(program)

        response = self.submit(program)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_PENDING_MODERATION)

    def test_non_draft_status_cannot_be_submitted(self):
        program = self.create_program(status=PartnerProgram.STATUS_PUBLISHED)
        self.accept_legal_terms(program)

        response = self.submit(program)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], PartnerProgram.STATUS_PUBLISHED)
        self.assertFalse(response.data["missing_required_sections"])


class PartnerProgramProjectApplyViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PartnerProgramProjectApplyView.as_view()
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user(
            email="leader@example.com",
            password="pass",
            first_name="Leader",
            last_name="User",
            birthday="1990-01-01",
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Program",
            "tag": f"program_{PartnerProgram.objects.count()}",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "draft": False,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now - timezone.timedelta(days=1),
            "datetime_finished": self.now + timezone.timedelta(days=30),
            "is_competitive": True,
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def create_profile(self, program, user=None):
        return PartnerProgramUserProfile.objects.create(
            user=user or self.user,
            partner_program=program,
            partner_program_data={},
        )

    def create_project(self, **overrides):
        defaults = {
            "leader": self.user,
            "draft": True,
            "is_public": False,
            "name": "Reusable Project",
        }
        defaults.update(overrides)
        return Project.objects.create(**defaults)

    def post_apply(self, program, data, user=None):
        request = self.factory.post(
            f"/partner-programs/{program.pk}/projects/apply/",
            data,
            format="json",
        )
        force_authenticate(request, user=user or self.user)
        return self.view(request, pk=program.pk)

    def test_apply_links_existing_leader_project(self):
        program = self.create_program()
        profile = self.create_profile(program)
        project = self.create_project()

        response = self.post_apply(program, {"project_id": project.id})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["project_id"], project.id)
        program_link = PartnerProgramProject.objects.get(
            partner_program=program,
            project=project,
        )
        self.assertEqual(response.data["program_link_id"], program_link.id)
        profile.refresh_from_db()
        self.assertEqual(profile.project_id, project.id)

    def test_apply_rejects_existing_project_from_another_leader(self):
        program = self.create_program()
        self.create_profile(program)
        other_user = get_user_model().objects.create_user(
            email="other@example.com",
            password="pass",
            first_name="Other",
            last_name="Leader",
            birthday="1990-01-01",
        )
        project = self.create_project(leader=other_user)

        response = self.post_apply(program, {"project_id": project.id})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            PartnerProgramProject.objects.filter(
                partner_program=program,
                project=project,
            ).exists()
        )

    def test_apply_rejects_project_already_linked_to_another_program(self):
        program = self.create_program()
        other_program = self.create_program()
        self.create_profile(program)
        project = self.create_project()
        PartnerProgramProject.objects.create(
            partner_program=other_program,
            project=project,
        )

        response = self.post_apply(program, {"project_id": project.id})

        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id", response.data)
        self.assertFalse(
            PartnerProgramProject.objects.filter(
                partner_program=program,
                project=project,
            ).exists()
        )


class PartnerProgramProjectSubmitViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PartnerProgramProjectSubmitView.as_view()
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user(
            email="leader@example.com",
            password="pass",
            first_name="Leader",
            last_name="User",
            birthday="1990-01-01",
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Program",
            "tag": "program_tag",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "draft": False,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now - timezone.timedelta(days=1),
            "datetime_finished": self.now + timezone.timedelta(days=30),
            "is_competitive": True,
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def create_project_link(self, program):
        project = Project.objects.create(
            leader=self.user,
            draft=False,
            is_public=False,
            name="Project",
        )
        return PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )

    def test_submit_blocked_after_deadline(self):
        program = self.create_program(
            datetime_project_submission_ends=self.now - timezone.timedelta(days=1)
        )
        link = self.create_project_link(program)

        request = self.factory.post(f"partner-program-projects/{link.pk}/submit/")
        force_authenticate(request, user=self.user)
        response = self.view(request, pk=link.pk)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data.get("detail"),
            "Срок подачи проектов в программу завершён.",
        )
        link.refresh_from_db()
        self.assertFalse(link.submitted)

    def test_submit_allowed_before_deadline(self):
        program = self.create_program(
            datetime_project_submission_ends=self.now + timezone.timedelta(days=1)
        )
        link = self.create_project_link(program)

        request = self.factory.post(f"partner-program-projects/{link.pk}/submit/")
        force_authenticate(request, user=self.user)
        response = self.view(request, pk=link.pk)

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertTrue(link.submitted)
        self.assertIsNotNone(link.datetime_submitted)

    def test_submit_rejects_project_that_violates_team_rules(self):
        program = self.create_program(
            datetime_project_submission_ends=self.now + timezone.timedelta(days=1),
            participation_format=PartnerProgram.PARTICIPATION_FORMAT_TEAM,
            project_team_min_size=2,
        )
        link = self.create_project_link(program)

        request = self.factory.post(f"partner-program-projects/{link.pk}/submit/")
        force_authenticate(request, user=self.user)
        response = self.view(request, pk=link.pk)

        self.assertEqual(response.status_code, 400)
        link.refresh_from_db()
        self.assertFalse(link.submitted)


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
        field = self.make_field("radio", is_required=True, options=["арбуз", "апельсин"])
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


class PartnerProgramDetailCoursesTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PartnerProgramDetail.as_view()
        self.now = timezone.now()

    def create_program(self, **overrides):
        defaults = {
            "name": "Program with courses",
            "tag": "program_with_courses",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "draft": False,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now - timezone.timedelta(days=1),
            "datetime_finished": self.now + timezone.timedelta(days=30),
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def create_user(self, email: str):
        return get_user_model().objects.create_user(
            email=email,
            password="pass",
            first_name="Test",
            last_name="User",
            birthday="1990-01-01",
        )

    def create_course(self, program: PartnerProgram, **overrides):
        defaults = {
            "title": "Program course",
            "partner_program": program,
            "access_type": CourseAccessType.ALL_USERS,
            "status": CourseContentStatus.PUBLISHED,
        }
        defaults.update(overrides)
        return Course.objects.create(**defaults)

    def test_detail_includes_related_courses_with_availability_for_member(self):
        program = self.create_program()
        member = self.create_user("member-program@example.com")
        PartnerProgramUserProfile.objects.create(
            user=member,
            partner_program=program,
            project=None,
            partner_program_data={},
        )
        all_users_course = self.create_course(
            program,
            title="Open course",
            access_type=CourseAccessType.ALL_USERS,
        )
        member_course = self.create_course(
            program,
            title="Members course",
            access_type=CourseAccessType.PROGRAM_MEMBERS,
        )
        self.create_course(
            program,
            title="Draft course",
            access_type=CourseAccessType.ALL_USERS,
            status=CourseContentStatus.DRAFT,
        )

        request = self.factory.get(f"/programs/{program.id}/")
        force_authenticate(request, user=member)
        response = self.view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["courses"],
            [
                {
                    "id": all_users_course.id,
                    "title": "Open course",
                    "is_available": True,
                },
                {
                    "id": member_course.id,
                    "title": "Members course",
                    "is_available": True,
                },
            ],
        )

    def test_detail_includes_empty_courses_list_when_program_has_no_related_courses(self):
        program = self.create_program()
        user = self.create_user("plain-user@example.com")

        request = self.factory.get(f"/programs/{program.id}/")
        force_authenticate(request, user=user)
        response = self.view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["courses"], [])

    def test_detail_marks_program_only_courses_as_unavailable_for_non_member(self):
        program = self.create_program()
        outsider = self.create_user("outsider-program@example.com")
        open_course = self.create_course(
            program,
            title="Open course",
            access_type=CourseAccessType.ALL_USERS,
        )
        member_course = self.create_course(
            program,
            title="Members course",
            access_type=CourseAccessType.PROGRAM_MEMBERS,
        )

        request = self.factory.get(f"/programs/{program.id}/")
        force_authenticate(request, user=outsider)
        response = self.view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["courses"],
            [
                {
                    "id": open_course.id,
                    "title": "Open course",
                    "is_available": True,
                },
                {
                    "id": member_course.id,
                    "title": "Members course",
                    "is_available": False,
                },
            ],
        )


class PartnerProgramDetailParticipantProjectTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = PartnerProgramDetail.as_view()
        self.now = timezone.now()

    def create_user(self, email: str):
        return get_user_model().objects.create_user(
            email=email,
            password="pass",
            first_name="Test",
            last_name="User",
            birthday="1990-01-01",
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Program with participant project",
            "tag": f"participant_project_{PartnerProgram.objects.count()}",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "draft": False,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now - timezone.timedelta(days=1),
            "datetime_finished": self.now + timezone.timedelta(days=30),
        }
        defaults.update(overrides)
        return PartnerProgram.objects.create(**defaults)

    def create_project(self, user, **overrides):
        defaults = {
            "leader": user,
            "draft": True,
            "is_public": False,
            "name": "Participant project",
            "description": "Project description",
            "presentation_address": "https://example.com/presentation.pdf",
        }
        defaults.update(overrides)
        return Project.objects.create(**defaults)

    def test_detail_includes_current_member_project_state(self):
        user = self.create_user("member-project@example.com")
        program = self.create_program()
        project = self.create_project(user)
        link = PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
        )
        PartnerProgramUserProfile.objects.create(
            user=user,
            partner_program=program,
            project=project,
            partner_program_data={},
        )

        request = self.factory.get(f"/programs/{program.id}/")
        force_authenticate(request, user=user)
        response = self.view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["program_link_id"], link.id)
        self.assertEqual(response.data["participant_project_status"], "not_submitted")
        self.assertIsNone(response.data["participant_project_submitted_at"])
        self.assertEqual(response.data["participant_project"]["id"], project.id)
        self.assertEqual(
            response.data["participant_project"]["partner_program"]["program_link_id"],
            link.id,
        )
        self.assertFalse(
            response.data["participant_project"]["partner_program"]["submitted"]
        )

    def test_detail_includes_submitted_project_state(self):
        user = self.create_user("submitted-project@example.com")
        program = self.create_program()
        project = self.create_project(user)
        submitted_at = timezone.now()
        link = PartnerProgramProject.objects.create(
            partner_program=program,
            project=project,
            submitted=True,
            datetime_submitted=submitted_at,
        )
        PartnerProgramUserProfile.objects.create(
            user=user,
            partner_program=program,
            project=project,
            partner_program_data={},
        )

        request = self.factory.get(f"/programs/{program.id}/")
        force_authenticate(request, user=user)
        response = self.view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["program_link_id"], link.id)
        self.assertEqual(response.data["participant_project_status"], "submitted")
        self.assertEqual(
            response.data["participant_project_submitted_at"],
            submitted_at.isoformat(),
        )
        self.assertTrue(
            response.data["participant_project"]["partner_program"]["submitted"]
        )

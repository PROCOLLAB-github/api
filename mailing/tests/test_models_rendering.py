from django.test import TestCase
from django.utils import timezone

from mailing.models import MailingScenarioLog
from mailing.rendering import render_subject, render_template_value
from mailing.views import MailingTemplateRender

from .helpers import create_mailing_schema, create_program, create_user


class MailingModelsTests(TestCase):
    def test_mailing_schema_string_representation(self):
        schema = create_mailing_schema(name="Program reminder")

        self.assertEqual(str(schema), "MailingSchema<Program reminder>")

    def test_mailing_scenario_log_string_representation(self):
        program = create_program()
        user = create_user()
        log = MailingScenarioLog.objects.create(
            scenario_code="program_registration_plus_3_inactive_account",
            program=program,
            user=user,
            scheduled_for=timezone.localdate(),
            status=MailingScenarioLog.Status.PENDING,
        )

        self.assertIn("program_registration_plus_3_inactive_account", str(log))
        self.assertIn(f"program={program.id}", str(log))
        self.assertIn(f"user={user.id}", str(log))
        self.assertIn("status=pending", str(log))


class MailingRenderingTests(TestCase):
    def test_render_subject_replaces_program_name(self):
        program = create_program(name="Case Cup")

        subject = render_subject("{program_name}: reminder", program)

        self.assertEqual(subject, "Case Cup: reminder")

    def test_render_template_value_replaces_known_placeholders(self):
        program = create_program(name="Case Cup")
        user = create_user()

        value = render_template_value(
            "/program/{program_id}/users/{user_id}/{program_name}",
            program,
            user,
        )

        self.assertEqual(value, f"/program/{program.id}/users/{user.id}/Case Cup")

    def test_template_render_context_contains_schema_users_and_fields(self):
        schema = create_mailing_schema(
            name="Participant email",
            schema={
                "title": {"title": "Title", "default": "Default title"},
                "text": {"title": "Text"},
            },
        )
        picked_user = create_user(email="picked@example.com")
        unpicked_user = create_user(email="unpicked@example.com")

        context = MailingTemplateRender._get_context(
            schema.id,
            picked_users=[picked_user],
            unpicked_users=[unpicked_user],
        )

        selected_schema = context["schemas"][0]
        self.assertEqual(selected_schema["id"], schema.id)
        self.assertTrue(selected_schema["selected"])
        self.assertEqual(context["picked_users"][0]["id"], picked_user.id)
        self.assertTrue(context["picked_users"][0]["picked"])
        self.assertEqual(context["unpicked_users"][0]["id"], unpicked_user.id)
        self.assertFalse(context["unpicked_users"][0]["picked"])
        self.assertEqual(
            context["template_fields"],
            [
                {"key": "title", "title": "Title", "default": "Default title"},
                {"key": "text", "title": "Text", "default": ""},
            ],
        )

from unittest.mock import Mock, patch

from django.test import TestCase

from mailing.typing import EmailDataToPrepare
from mailing.utils import (
    create_message_groups,
    prepare_mail_data,
    send_mass_mail,
    send_mass_mail_from_template,
)

from .helpers import create_mailing_schema, create_user


class MailingPrepareDataTests(TestCase):
    def test_prepare_mail_data_from_dataclass_uses_schema_and_requested_users(self):
        user = create_user("recipient@example.com")
        other_user = create_user("other@example.com")
        schema = create_mailing_schema(
            schema={
                "title": {"title": "Title"},
                "text": {"title": "Text"},
            },
            template="<h1>{{ title }}</h1><p>{{ text }}</p>",
        )

        mail_data = prepare_mail_data(
            EmailDataToPrepare(
                users_ids=[user.id],
                subject="Subject",
                schema_id=schema.id,
                context_data={
                    "title": "Custom title",
                    "text": "Custom text",
                    "button_link": "https://example.com",
                    "button_text": "Open",
                },
            )
        )

        self.assertEqual(list(mail_data["users"]), [user])
        self.assertNotIn(other_user, list(mail_data["users"]))
        self.assertEqual(mail_data["subject"], "Subject")
        self.assertEqual(mail_data["template_string"], schema.template)
        self.assertEqual(
            mail_data["template_context"],
            {"title": "Custom title", "text": "Custom text"},
        )


class MailingSendUtilsTests(TestCase):
    def test_create_message_groups_uses_configured_batch_size(self):
        messages = list(range(205))

        groups = create_message_groups(messages)

        self.assertEqual([len(group) for group in groups], [100, 100, 5])

    @patch("mailing.utils.send_group_messages")
    def test_send_mass_mail_renders_template_for_each_user(self, send_group_messages):
        send_group_messages.side_effect = lambda messages: len(messages)
        first_user = create_user("first@example.com")
        second_user = create_user("second@example.com")

        sent_count = send_mass_mail(
            [first_user, second_user],
            "Subject",
            "Hello {{ user.email }}: {{ title }}",
            {"title": "Reminder"},
        )

        self.assertEqual(sent_count, 2)
        send_group_messages.assert_called_once()
        messages = send_group_messages.call_args.args[0]
        self.assertEqual(messages[0].to, [first_user.email])
        self.assertEqual(messages[0].subject, "Subject")
        self.assertIn("Hello first@example.com: Reminder", messages[0].body)
        self.assertEqual(messages[1].to, [second_user.email])
        self.assertIn("Hello second@example.com: Reminder", messages[1].body)

    @patch("mailing.utils.send_group_messages")
    @patch("mailing.utils.get_template")
    def test_send_mass_mail_from_template_calls_status_callback(
        self,
        get_template,
        send_group_messages,
    ):
        template = Mock()
        template.render.side_effect = lambda context: f"Hello {context['user'].email}"
        get_template.return_value = template
        send_group_messages.side_effect = lambda messages: len(messages)
        user = create_user("template-recipient@example.com")
        handled_user_ids = []

        sent_count = send_mass_mail_from_template(
            [user],
            "Subject",
            "email/template.html",
            status_callback=lambda handled_user, msg: handled_user_ids.append(
                handled_user.id
            ),
        )

        self.assertEqual(sent_count, 1)
        get_template.assert_called_once_with("email/template.html")
        self.assertEqual(handled_user_ids, [user.id])
        message = send_group_messages.call_args.args[0][0]
        self.assertEqual(message.to, [user.email])
        self.assertIn("Hello template-recipient@example.com", message.body)

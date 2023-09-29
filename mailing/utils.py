import pathlib
from typing import Union, List, Dict

import django.db.models
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from users.models import CustomUser


class MailSender:
    @staticmethod
    def send(
        users: django.db.models.QuerySet | List[CustomUser],
        subject: str,
        template_path: str,
        template_context: Union[
            Dict,
            List,
        ] = None,
        connection=None,
    ) -> None:
        """
        Begin mailing to specified users, sending rendered template with template_text arg.
        Throws an error if template render is unsuccessful.
        Args:
            users: - The list of users who should receive the email.
            template_path: Template path.
            subject: Subject of mail.
            template_context: Context for template render.
            connection: Connection to mail backend
        """
        if template_context is None:
            template_context = {}
        template_path = pathlib.Path(template_path).absolute()
        html_msg = render_to_string(template_path, template_context)
        plain_msg = render_to_string(template_path, template_context)
        emails = [user.email for user in users]
        data = [
            (subject, plain_msg, None, [recipient_email], html_msg)
            for recipient_email in emails
        ]

        connection = connection or mail.get_connection()
        messages = []
        for subject, message, sender, recipient, html_msg in data:
            msg = EmailMultiAlternatives(
                subject, message, sender, recipient, connection=connection
            )
            msg.attach_alternative(html_msg, "text/html")
            messages.append(msg)
        return connection.send_messages(messages)

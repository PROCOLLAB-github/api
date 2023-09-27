from typing import Union, List, Dict

import django.db.models
from django.core import mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from users.models import CustomUser


class MailSender:
    @staticmethod
    def send(
        users: Union[django.db.models.QuerySet, List[CustomUser]],
        subject: str,
        template_name: str,
        template_context: Union[
            Dict,
            List,
        ] = None,
    ) -> None:
        """
        Begin mailing to specified users, sending rendered template with template_text arg.
        Throws an error if template render is unsuccessful.
        Args:
            users: - The list of users who should receive the email.
            template: Template name, templates are stored in templates/email.
            subject: Subject of mail.
            template_context: Context for template render.
        """
        if template_context is None:
            template_context = {}
        html_msg = render_to_string(f"templates/email/{template_name}", template_context)
        plain_msg = strip_tags(html_msg)
        emails = [
            user.email for user in users if hasattr(user, "email") and user.email != ""
        ]
        mail.send_mail("My subject", plain_msg, None, emails, html_message=html_msg)

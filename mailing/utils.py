import pathlib
from typing import Union, List, Dict

import django.db.models
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from users.models import CustomUser


def send_mail(
    user: CustomUser,
    subject: str,
    template_path: str,
    template_context: Union[
        Dict,
        List,
    ] = None,
    connection=None,
):
    return send_mails_mass([user], subject, template_path, template_context, connection)


def send_mails_mass(
    users: django.db.models.QuerySet,
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
        template_path: str of template_path
        subject: Subject of mail.
        template_context: Context for template render.
        connection: Connection to mail backend
    """
    if template_context is None:
        template_context = {}
    template_path = pathlib.Path(template_path).absolute()
    connection = connection or mail.get_connection()
    messages = []
    for user in users:
        template_context["user"] = user
        html_msg = render_to_string(template_path, template_context)
        plain_msg = render_to_string(template_path, template_context)
        msg = EmailMultiAlternatives(
            subject, plain_msg, None, [user.email], connection=connection
        )
        msg.attach_alternative(html_msg, "text/html")
        messages.append(msg)
    return connection.send_messages(messages)

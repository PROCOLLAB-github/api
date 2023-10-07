from typing import Dict, List, Union

import django.db.models
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template

User = get_user_model()


def send_mail(
    user: User,
    subject: str,
    template_string: str,
    template_context: Union[
        Dict,
        List,
    ] = None,
    connection=None,
):
    return send_mass_mail([user], subject, template_string, template_context, connection)


def send_mass_mail(
    users: django.db.models.QuerySet | List[User],
    subject: str,
    template_string: str,
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
        template_string: str of template_path
        subject: Subject of mail.
        template_context: Context for template render.
        connection: Connection to mail backend
    """
    if template_context is None:
        template_context = {}

    connection = connection or mail.get_connection()
    template = Template(template_string)
    messages = []
    for user in users:
        template_context["user"] = user
        html_msg = template.render(Context(template_context))
        plain_msg = template.render(Context(template_context))
        msg = EmailMultiAlternatives(
            subject, plain_msg, None, [user.email], connection=connection
        )
        msg.attach_alternative(html_msg, "text/html")
        messages.append(msg)
    return connection.send_messages(messages)

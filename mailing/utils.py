from functools import singledispatch
from typing import Dict, List, Union, Annotated

from procollab import settings
from .constants import MAILING_USERS_BATCH_SIZE
from .models import MailingSchema
from users.models import CustomUser

import django.db.models
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template

from .typing import MailDataDict, EmailDataToPrepare

User = get_user_model()


@singledispatch
def prepare_mail_data(post_data):
    users = post_data.getlist("users[]")
    schema_id = post_data["schemas"]
    subject = post_data["subject"]
    mail_schema = MailingSchema.objects.get(pk=schema_id)
    context = {}
    for variable_name in mail_schema.schema:
        key_in_post = "field-" + variable_name
        if key_in_post in post_data:
            context[variable_name] = post_data[key_in_post]
    users_to_send = CustomUser.objects.filter(pk__in=users)
    return {
        "users_to_send": users_to_send,
        "subject": subject,
        "mail_schema_template": mail_schema.template,
        "context": context,
    }


@prepare_mail_data.register(EmailDataToPrepare)
def _(post_data: EmailDataToPrepare) -> MailDataDict:
    schema_id = post_data.schema_id
    subject = post_data.subject
    mail_schema = MailingSchema.objects.get(pk=schema_id)
    context = {}
    for variable_name in mail_schema.schema:
        if variable_name in post_data.context_data:
            context[variable_name] = post_data.context_data[variable_name]

    users_to_send = CustomUser.objects.filter(pk__in=post_data.users_ids)
    return {
        "users": users_to_send,
        "subject": subject,
        "template_string": mail_schema.template,
        "template_context": context,
    }


def create_message_groups(messages: list) -> list[list]:
    grouped_messages: list[list] = [
        messages[message : message + MAILING_USERS_BATCH_SIZE]  # noqa: E203
        for message in range(0, len(messages), MAILING_USERS_BATCH_SIZE)
    ]
    return grouped_messages


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


def send_group_messages(messages: list) -> int:
    connection = mail.get_connection()
    num_sent = connection.send_messages(messages)
    connection.close()
    return num_sent


def send_mass_mail(
    users: django.db.models.QuerySet | List[User],
    subject: str,
    template_string: str,
    template_context: Union[
        MailDataDict,
        list,
    ] = None,
    connection=None,
) -> Annotated[int, "Количество отосланных сообщений"]:
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

    template = Template(template_string)
    messages = []
    for user in users:
        template_context["user"] = user
        html_msg = template.render(Context(template_context))
        plain_msg = template.render(Context(template_context))
        msg = EmailMultiAlternatives(
            subject, plain_msg, settings.EMAIL_USER, [user.email]
        )
        msg.attach_alternative(html_msg, "text/html")
        messages.append(msg)

    grouped_messages = create_message_groups(messages)
    num_sent: int = 0
    for group in grouped_messages:
        num_sent += send_group_messages(group)
    return num_sent


def send_mass_mail_from_template(
    users: django.db.models.QuerySet | List[User],
    subject: str,
    template_name: str,
    template_context: Union[
        MailDataDict,
        list,
        dict,
    ] = None,
    context_builder=None,
    connection=None,
) -> Annotated[int, "Количество отосланных сообщений"]:
    """
    Send emails using a template file from Django template loaders.
    Allows optional per-user context via context_builder(user) -> dict.
    """
    if template_context is None:
        template_context = {}

    template = get_template(template_name)
    messages = []
    for user in users:
        context = dict(template_context)
        if context_builder is not None:
            context.update(context_builder(user))
        context["user"] = user
        html_msg = template.render(context)
        plain_msg = template.render(context)
        msg = EmailMultiAlternatives(
            subject, plain_msg, settings.EMAIL_USER, [user.email]
        )
        msg.attach_alternative(html_msg, "text/html")
        messages.append(msg)

    grouped_messages = create_message_groups(messages)
    num_sent: int = 0
    for group in grouped_messages:
        num_sent += send_group_messages(group)
    return num_sent

import datetime

from mailing.definitions import EmailDataToPrepare, ContextDataDict, MailDataDict
from mailing.utils import send_mass_mail, prepare_mail_data
from procollab.celery import app
from vacancy.mapping import (
    CeleryEmailParams,
    create_text_for_email,
    message_type_to_button_text,
    get_link,
    MessageTypeEnum,
    message_type_to_title,
    EmailParamsType,
)
from vacancy.models import Vacancy


@app.task
def send_email(data: EmailParamsType):
    context_data = ContextDataDict(
        text=create_text_for_email(data),
        title=message_type_to_title[data["message_type"]],
        button_link=get_link(data),
        button_text=message_type_to_button_text[data["message_type"]],
    )
    mail_data: MailDataDict = prepare_mail_data(
        EmailDataToPrepare(
            users_ids=[data["user_id"]],
            schema_id=data["schema_id"],
            subject=message_type_to_title[data["message_type"]],
            context_data=context_data,
        )
    )
    send_mass_mail(**mail_data)


@app.task
def email_notificate_vacancy_outdated():
    """Уведомление лидера по email о том, что вакансия просрочилась"""
    expiration_check = datetime.datetime.now() - datetime.timedelta(days=30)

    outdated_active_vacancies = Vacancy.objects.select_related(
        "project", "project__leader"
    ).filter(is_active=True, datetime_created__lte=expiration_check)

    for vacancy in outdated_active_vacancies:
        project = vacancy.project
        data_to_send = CeleryEmailParams(
            message_type=MessageTypeEnum.OUTDATED.value,
            user_id=project.leader.id,
            project_name=project.name,
            project_id=project.id,
            vacancy_role=vacancy.role,
            schema_id=2,
        )
        send_email.delay(data_to_send)
    outdated_active_vacancies.update(is_active=False)

from mailing.constants import VACANCY_ACCEPT_SUBJECT, VACANCY_RECEIVE_RESPONSE
from mailing.typing import DataToPrepare, ContextDataDict, MailDataDict
from mailing.utils import send_mass_mail, prepare_mail_data
from procollab.celery import app


@app.task
def email_notificate_vacancy_accepted(
    user_id: int,
    project_name: str,
    project_id: int,
    vacancy_role: str,
    schema_id: int = 2,
):
    """Уведомление откликнувшегося по email о том, его его ваканси. одобрили"""

    text = f"""
    Ваш отклик на роль {vacancy_role} в проекте "{project_name}" не остался незамеченным.
    Вас готовы принять в команду!
    """
    context_data: ContextDataDict = dict(
        text=text,
        title=VACANCY_ACCEPT_SUBJECT,
        button_link=f"https://app.procollab.ru/office/projects/{project_id}",
        button_text="Посмотреть проект",
    )
    mail_data: MailDataDict = prepare_mail_data(
        DataToPrepare(
            users_ids=[user_id],
            schema_id=schema_id,
            subject=VACANCY_ACCEPT_SUBJECT,
            context_data=context_data,
        )
    )
    send_mass_mail(**mail_data)


@app.task
def email_notificate_vac_response_created(
    user_id: int,
    project_name: str,
    project_id: int,
    vacancy_role: str,
    schema_id: int = 2,
):
    """Уведомление лидера по email о том, что кто-то откликнулся на вакансию его проекта"""

    text = f"""
    На вакансию {vacancy_role} для проекта "{project_name}" оставили отклик.
    """
    context_data: ContextDataDict = dict(
        text=text,
        title=VACANCY_RECEIVE_RESPONSE,
        button_link=f"https://app.procollab.ru/office/projects/{project_id}/responses",
        button_text="Посмотреть на отклики",
    )
    mail_data: MailDataDict = prepare_mail_data(
        DataToPrepare(
            users_ids=[user_id],
            schema_id=schema_id,
            subject=VACANCY_RECEIVE_RESPONSE,
            context_data=context_data,
        )
    )
    send_mass_mail(**mail_data)

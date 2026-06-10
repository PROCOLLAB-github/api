from unittest.mock import patch

from django.test import TestCase

from vacancy.mapping import (
    MessageTypeEnum,
    create_text_for_email,
    get_link,
)
from vacancy.tasks import email_notificate_vacancy_outdated, send_email
from vacancy.tests.helpers import create_old_vacancy, create_project, create_user


class VacancyEmailMappingTests(TestCase):
    def test_responded_email_points_to_project_responses(self):
        data = {
            "message_type": MessageTypeEnum.RESPONDED.value,
            "user_id": 1,
            "project_name": "Проект",
            "project_id": 10,
            "vacancy_role": "Backend",
            "schema_id": 2,
        }

        self.assertEqual(
            get_link(data),
            "https://app.procollab.ru/office/projects/10/responses",
        )
        self.assertIn("Backend", create_text_for_email(data))

    @patch("vacancy.tasks.send_mass_mail")
    @patch("vacancy.tasks.prepare_mail_data")
    def test_send_email_prepares_and_sends_mail(self, prepare_mail_data, send_mass_mail):
        prepare_mail_data.return_value = {"messages": ["mail"]}
        data = {
            "message_type": MessageTypeEnum.ACCEPTED.value,
            "user_id": 1,
            "project_name": "Проект",
            "project_id": 10,
            "vacancy_role": "Backend",
            "schema_id": 2,
        }

        send_email(data)

        prepare_mail_data.assert_called_once()
        send_mass_mail.assert_called_once_with(messages=["mail"])


class OutdatedVacancyTaskTests(TestCase):
    @patch("vacancy.tasks.send_email.delay")
    def test_outdated_task_notifies_leaders_and_closes_old_active_vacancies(
        self,
        send_email_delay,
    ):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        old_vacancy = create_old_vacancy(project=project, is_active=True, days=31)
        fresh_vacancy = create_old_vacancy(project=project, is_active=True, days=10)

        email_notificate_vacancy_outdated()

        old_vacancy.refresh_from_db()
        fresh_vacancy.refresh_from_db()
        self.assertFalse(old_vacancy.is_active)
        self.assertTrue(fresh_vacancy.is_active)
        send_email_delay.assert_called_once()
        self.assertEqual(send_email_delay.call_args.args[0]["user_id"], leader.id)

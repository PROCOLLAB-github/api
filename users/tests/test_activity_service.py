from django.test import TestCase

from users.services.users_activity import UserActivityDataPreparer

from .helpers import add_user_to_program, build_partner_program, build_project, build_user


class UserActivityDataPreparerTests(TestCase):
    def test_activity_data_counts_program_membership_and_program_project_separately(self):
        user = build_user(email="activity-report@example.com")
        program = build_partner_program()
        add_user_to_program(user, program)

        data = UserActivityDataPreparer().get_users_prepared_data()
        user_row = next(row for row in data if row["ID пользователя"] == user.id)

        self.assertEqual(user_row["Участие в программах кол-во"], 1)
        self.assertEqual(user_row["Кол-во проектов в программе"], 0)

    def test_activity_data_counts_project_submitted_to_program(self):
        user = build_user(email="activity-project@example.com")
        project = build_project(user)
        program = build_partner_program(tag="project-program")
        add_user_to_program(user, program, project=project)

        data = UserActivityDataPreparer().get_users_prepared_data()
        user_row = next(row for row in data if row["ID пользователя"] == user.id)

        self.assertEqual(user_row["Участие в программах кол-во"], 1)
        self.assertEqual(user_row["Кол-во проектов в программе"], 1)

from django.test import TestCase

from users.models import CustomUser

from .helpers import attach_skill, build_skill, build_specialization, build_user


class UserSignalsTests(TestCase):
    def test_dataset_migration_flag_is_enabled_when_specialization_and_skills_exist(self):
        user = build_user(email="dataset@example.com")
        user.v2_speciality = build_specialization()
        attach_skill(user, build_skill())

        with self.captureOnCommitCallbacks(execute=True):
            user.save()
        user.refresh_from_db()

        self.assertTrue(user.dataset_migration_applied)

    def test_role_signal_creates_expected_profile_for_non_member_types(self):
        mentor = build_user(email="mentor@example.com", user_type=CustomUser.MENTOR)
        investor = build_user(email="investor@example.com", user_type=CustomUser.INVESTOR)

        self.assertTrue(hasattr(mentor, "mentor"))
        self.assertTrue(hasattr(investor, "investor"))

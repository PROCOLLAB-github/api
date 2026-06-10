from django.test import TestCase

from invites.tests.helpers import create_invite


class InviteModelTests(TestCase):
    def test_string_representation_contains_project_and_user(self):
        invite = create_invite()

        self.assertEqual(
            str(invite),
            (
                f'Invite from project "{invite.project.name}" '
                f"to {invite.user.get_full_name()}"
            ),
        )

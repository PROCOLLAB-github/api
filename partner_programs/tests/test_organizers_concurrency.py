from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import OrganizerInvitation
from partner_programs.services.organizers import revision
from project_rates.tests.helpers import create_rate_program, create_rate_user
from project_rates.workspace import digest


@skipUnlessDBFeature("has_select_for_update")
class OrganizerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.program = create_rate_program()
        self.first = create_rate_user()
        self.second = create_rate_user()
        self.program.managers.add(self.first, self.second)
        self.root = f"/programs/{self.program.pk}/management/"

    def parallel(self, calls):
        gate = Barrier(2)

        def run(call):
            connections.close_all()
            try:
                gate.wait(timeout=10)
                return call()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, calls))

    def test_simultaneous_self_exit_leaves_one_organizer(self):
        expected = revision(self.program)

        def leave(user):
            client = APIClient()
            client.force_authenticate(user)
            return client.post(
                self.root + f"organizers/{user.pk}/remove/",
                {"revision": expected},
                format="json",
            ).status_code

        result = self.parallel([lambda: leave(self.first), lambda: leave(self.second)])
        self.assertEqual(sorted(result), [200, 409])
        self.assertEqual(self.program.managers.count(), 1)

    def test_acceptance_racing_with_revocation_has_one_valid_outcome(self):
        self.program.managers.remove(self.second)
        token = "a" * 43
        invitation = OrganizerInvitation.objects.create(
            partner_program=self.program,
            email=self.second.email,
            invited_by=self.first,
            token_digest=digest(token),
            expires_at=timezone.now() + timedelta(days=1),
        )
        expected = revision(self.program)

        def accept():
            client = APIClient()
            client.force_authenticate(self.second)
            return client.post(
                f"/programs/organizer-invitations/{token}/accept/", {}, format="json"
            ).status_code

        def revoke():
            client = APIClient()
            client.force_authenticate(self.first)
            return client.post(
                self.root + f"organizer-invitations/{invitation.pk}/revoke/",
                {"revision": expected},
                format="json",
            ).status_code

        accepted, revoked = self.parallel([accept, revoke])
        self.assertIn((accepted, revoked), [(200, 409), (410, 200)])
        invitation.refresh_from_db()
        self.assertEqual(
            self.program.is_manager(self.second), invitation.status == "accepted"
        )

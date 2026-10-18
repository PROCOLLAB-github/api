from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from project_rates.models import ExpertInvitation, ProjectExpertAssignment
from project_rates.tests.helpers import (
    create_rate_program,
    create_rate_user,
    create_rate_expert,
    create_rate_project,
    link_project_to_program,
)
from project_rates.workspace import digest, revision
from users.models import CustomUser


@skipUnlessDBFeature("has_select_for_update")
class WorkspaceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.program = create_rate_program(
            required_evaluators=2, is_distributed_evaluation=True
        )
        self.manager = create_rate_user()
        self.program.managers.add(self.manager)

    def test_concurrent_project_and_legacy_assignment_cannot_overfill_last_place(self):
        self.program.required_evaluators = 1
        self.program.save()
        experts = [create_rate_expert(program=self.program) for _ in range(2)]
        project = create_rate_project()
        link = link_project_to_program(self.program, project)
        type(link).objects.filter(pk=link.pk).update(submitted=True)
        root = f"/programs/{self.program.pk}/management/"
        rev = revision(self.program)
        gate = Barrier(2)

        def assign(index):
            connections.close_all()
            try:
                client = APIClient()
                client.force_authenticate(self.manager)
                gate.wait(timeout=10)
                if index == 0:
                    return client.post(
                        root + "project-experts/",
                        {
                            "revision": rev,
                            "project_ids": [project.pk],
                            "expert_ids": [experts[index].expert.pk],
                            "mode": "add",
                        },
                        format="json",
                    ).status_code
                return client.put(
                    root + f"experts/{experts[index].expert.pk}/assignments/",
                    {"revision": rev, "project_ids": [project.pk]},
                    format="json",
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(assign, range(2)))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(
            ProjectExpertAssignment.objects.filter(partner_program=self.program).count(),
            1,
        )

    def test_two_registration_submits_create_one_account(self):
        token = "concurrent-invitation-token-0123456789"
        email = "concurrent-expert@example.com"
        ExpertInvitation.objects.create(
            partner_program=self.program,
            email=email,
            token_digest=digest(token),
            expires_at=timezone.now() + timedelta(days=7),
        )
        gate = Barrier(2)

        def register():
            connections.close_all()
            try:
                gate.wait(timeout=10)
                client = APIClient()
                return client.post(
                    f"/evaluation/invitations/{token}/register/",
                    dict(
                        first_name="Анна",
                        last_name="Волкова",
                        password="SafeExpert234!",
                        repeat_password="SafeExpert234!",
                        accept_policy=True,
                        accept_age=True,
                    ),
                    format="json",
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: register(), range(2)))
        self.assertEqual(sorted(statuses), [201, 410])
        self.assertEqual(CustomUser.objects.filter(email=email).count(), 1)
        self.assertEqual(self.program.experts.filter(user__email=email).count(), 1)

    def test_concurrent_manual_save_and_auto_apply_reject_stale_writer(self):
        expert = create_rate_expert(program=self.program)
        other = create_rate_expert(program=self.program)
        project = create_rate_project()
        link = link_project_to_program(self.program, project)
        type(link).objects.filter(pk=link.pk).update(submitted=True)
        root = f"/programs/{self.program.pk}/management/"
        client = APIClient()
        client.force_authenticate(self.manager)
        preview = client.post(
            root + "expert-allocation/",
            {"expert_ids": [expert.expert.pk, other.expert.pk]},
            format="json",
        )
        self.assertEqual(preview.status_code, 200, preview.data)
        rev = revision(self.program)
        gate = Barrier(2)

        def save(manual):
            connections.close_all()
            try:
                inner = APIClient()
                inner.force_authenticate(self.manager)
                gate.wait(timeout=10)
                if manual:
                    return inner.put(
                        root + f"experts/{expert.expert.pk}/assignments/",
                        {"revision": rev, "project_ids": [project.pk]},
                        format="json",
                    ).status_code
                return inner.post(
                    root + "expert-allocation/apply/",
                    {"plan_token": preview.data["plan_token"]},
                    format="json",
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(save, [True, False]))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertIn(
            ProjectExpertAssignment.objects.filter(partner_program=self.program).count(),
            [1, 2],
        )

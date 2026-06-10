from types import SimpleNamespace

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from invites.filters import InviteFilter
from invites.models import Invite
from invites.tests.helpers import (
    add_collaborator,
    add_user_to_program,
    create_invite,
    create_project,
    create_user,
    invite_payload,
    link_project_to_program,
)


class InviteCreateAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_project_leader_can_create_invite(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient, role="Designer"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["project"]["id"], project.id)
        self.assertEqual(response.data["user"]["id"], recipient.id)
        self.assertEqual(response.data["sender"]["id"], leader.id)
        self.assertEqual(response.data["role"], "Designer")
        self.assertIsNone(response.data["is_accepted"])

    def test_project_leader_can_create_invite_without_motivational_letter(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient, motivational_letter=None),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["motivational_letter"])

    def test_non_leader_cannot_create_invite(self):
        leader = create_user(prefix="leader")
        outsider = create_user(prefix="outsider")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        self.client.force_authenticate(outsider)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Invite.objects.exists())

    def test_create_invite_requires_payload(self):
        leader = create_user(prefix="leader")
        self.client.force_authenticate(leader)

        response = self.client.post("/invites/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Invite.objects.exists())

    def test_cannot_invite_project_leader(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, leader),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("user", response.data)

    def test_cannot_invite_existing_collaborator(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        add_collaborator(project=project, user=recipient)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("user", response.data)

    def test_cannot_create_duplicate_active_invite(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        create_invite(project=project, user=recipient)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Invite.objects.filter(project=project, user=recipient).count(), 1)

    def test_program_project_invite_requires_program_membership(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        link_project_to_program(project=project)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("user", response.data)

    def test_program_member_can_be_invited_to_program_project(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        program = link_project_to_program(project=project)
        add_user_to_program(user=recipient, program=program)
        self.client.force_authenticate(leader)

        response = self.client.post(
            "/invites/",
            invite_payload(project, recipient),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["id"], recipient.id)


class InviteListFilterAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_list_returns_current_user_active_invites_by_default(self):
        user = create_user(prefix="recipient")
        own_invite = create_invite(user=user)
        create_invite()
        create_invite(user=user, is_accepted=True)
        create_invite(user=user, is_accepted=False)
        self.client.force_authenticate(user)

        response = self.client.get("/invites/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [own_invite.id])

    def test_list_can_filter_by_project(self):
        user = create_user(prefix="recipient")
        project = create_project()
        target_invite = create_invite(project=project, user=user)
        create_invite(user=user)
        self.client.force_authenticate(user)

        response = self.client.get("/invites/", {"project": project.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [target_invite.id])

    def test_user_filter_does_not_expose_foreign_invites(self):
        user = create_user(prefix="recipient")
        other_user = create_user(prefix="other")
        create_invite(user=other_user)
        self.client.force_authenticate(user)

        response = self.client.get("/invites/", {"user": other_user.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_user_any_filter_is_forbidden_for_regular_user(self):
        user = create_user(prefix="recipient")
        create_invite(user=user)
        create_invite()
        create_invite(is_accepted=True)
        self.client.force_authenticate(user)

        response = self.client.get("/invites/", {"user": "any"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_leader_can_list_project_invites_by_project_filter(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        first_invite = create_invite(project=project)
        second_invite = create_invite(project=project)
        create_invite()
        self.client.force_authenticate(leader)

        response = self.client.get("/invites/", {"project": project.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in response.data},
            {first_invite.id, second_invite.id},
        )

    def test_project_leader_can_list_invite_after_creating_via_api(self):
        leader = create_user(prefix="leader")
        recipient = create_user(prefix="recipient")
        project = create_project(leader=leader)
        self.client.force_authenticate(leader)

        create_response = self.client.post(
            "/invites/",
            invite_payload(project, recipient),
            format="json",
        )
        list_response = self.client.get("/invites/", {"project": project.id})

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in list_response.data],
            [create_response.data["id"]],
        )

    def test_project_filter_handles_scalar_multi_digit_project_id(self):
        leader = create_user(prefix="leader")
        projects = [create_project(leader=leader) for _ in range(12)]
        target_project = projects[-1]
        invite = create_invite(project=target_project)

        filtered = InviteFilter(
            data={"project": str(target_project.id)},
            queryset=Invite.objects.all(),
            request=SimpleNamespace(user=leader),
        ).qs

        self.assertEqual(list(filtered), [invite])

    def test_project_leader_cannot_use_user_any_filter(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        create_invite(project=project)
        self.client.force_authenticate(leader)

        response = self.client.get(
            "/invites/",
            {"project": project.id, "user": "any"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_leader_can_filter_project_invites_by_invited_user(self):
        leader = create_user(prefix="leader")
        project = create_project(leader=leader)
        recipient = create_user(prefix="recipient")
        target_invite = create_invite(project=project, user=recipient)
        create_invite(project=project)
        create_invite()
        self.client.force_authenticate(leader)

        response = self.client.get(
            "/invites/",
            {"project": project.id, "user": recipient.id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [target_invite.id])

    def test_staff_can_list_all_active_invites_with_user_any(self):
        staff = create_user(prefix="staff", is_staff=True)
        first_invite = create_invite()
        second_invite = create_invite()
        create_invite(is_accepted=True)
        self.client.force_authenticate(staff)

        response = self.client.get("/invites/", {"user": "any"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in response.data},
            {first_invite.id, second_invite.id},
        )

    def test_anonymous_user_cannot_list_invites(self):
        create_invite()

        response = self.client.get("/invites/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

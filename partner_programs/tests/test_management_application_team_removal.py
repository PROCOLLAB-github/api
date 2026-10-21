from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core import signing
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from chats.consumers import ChatConsumer
from chats.models import ProjectChat
from invites.models import Invite
from partner_programs.models import PartnerProgramProject, PartnerProgramUserProfile
from partner_programs.services.participant_removal import (
    preview_removal,
    remove_participants,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_project,
    create_user,
)
from project_rates.models import Criteria, ProjectExpertAssignment, ProjectScore
from project_rates.tests.helpers import create_rate_expert
from projects.models import Collaborator, Project


class ApplicationTeamFixture:
    def seed(self):
        self.manager = create_user()
        self.program = create_partner_program(
            is_competitive=True, is_distributed_evaluation=True, legacy_team_min_size=1
        )
        self.program.managers.add(self.manager)
        self.leader = create_program_member(self.program)
        self.member = create_program_member(self.program)
        self.foreign = create_partner_program()
        self.foreign_member = create_program_member(self.foreign, user=self.member.user)
        create_program_member(self.foreign, user=self.leader.user)
        self.source = create_project(
            leader=self.leader.user, name="Исходный проект", draft=False, is_public=True
        )
        Collaborator.objects.create(project=self.source, user=self.member.user)
        self.source_link = PartnerProgramProject.objects.create(
            partner_program=self.foreign, project=self.source
        )
        self.source_invite = Invite.objects.create(
            project=self.source, user=self.member.user, is_accepted=True
        )
        self.client = APIClient()
        self.client.force_authenticate(self.leader.user)
        response = self.client.post(
            "/projects/assign-to-program/",
            {"project_id": self.source.pk, "partner_program_id": self.program.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.project = Project.objects.get(pk=response.data["new_project_id"])
        self.link = PartnerProgramProject.objects.get(pk=response.data["program_link_id"])
        self.assertNotEqual(self.source.pk, self.project.pk)
        self.project.draft = False
        self.project.save(update_fields=["draft"])
        self.invite = Invite.objects.create(
            project=self.project,
            program_link=self.link,
            user=self.member.user,
            is_accepted=True,
        )
        self.root = f"/programs/{self.program.pk}/management/participants/"
        self.client.force_authenticate(self.manager)

    def preview(self, ids=None):
        response = self.client.post(
            self.root + "remove-preview/", {"ids": ids or [self.member.pk]}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def remove(self, preview, ids=None, version=2):
        return self.client.post(
            self.root + "remove/",
            {
                "ids": ids or [self.member.pk],
                "preview_token": preview["preview_token"],
                "confirmation_version": version,
            },
            format="json",
        )


class ApplicationTeamRemovalTests(ApplicationTeamFixture, TestCase):
    def setUp(self):
        self.seed()

    def test_pending_invitation_without_team_membership_is_revoked(self):
        Collaborator.objects.filter(project=self.project, user=self.member.user).delete()
        Invite.objects.filter(pk=self.invite.pk).delete()
        self.invite = Invite.objects.create(
            project=self.project, program_link=self.link, user=self.member.user
        )
        preview = self.preview()
        self.assertEqual(preview["team_changes"][0]["members"], [])
        self.assertEqual(preview["team_changes"][0]["invitations_count"], 1)
        response = self.remove(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Invite.objects.filter(pk=self.invite.pk).exists())
        self.client.force_authenticate(self.member.user)
        self.assertEqual(
            self.client.get(f"/projects/{self.project.pk}/").status_code, 403
        )
        self.assertTrue(Invite.objects.filter(pk=self.source_invite.pk).exists())

    def test_real_duplicate_loses_member_but_source_and_other_program_are_unchanged(self):
        preview = self.preview()
        self.assertEqual(preview["confirmation_version"], 2)
        self.assertEqual(preview["applications"], [])
        self.assertEqual(preview["team_changes"][0]["project_id"], self.project.pk)
        self.assertEqual(
            preview["team_changes"][0]["members"][0]["id"], self.member.user_id
        )
        self.assertEqual(preview["team_changes"][0]["invitations_count"], 1)
        response = self.remove(preview)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["removed_team_members"], 1)
        self.assertFalse(
            PartnerProgramUserProfile.objects.filter(pk=self.member.pk).exists()
        )
        self.assertFalse(
            Collaborator.objects.filter(
                project=self.project, user=self.member.user
            ).exists()
        )
        self.assertFalse(Invite.objects.filter(pk=self.invite.pk).exists())
        self.assertTrue(
            Collaborator.objects.filter(
                project=self.source, user=self.member.user
            ).exists()
        )
        self.assertTrue(Invite.objects.filter(pk=self.source_invite.pk).exists())
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=self.foreign_member.pk).exists()
        )
        self.assertTrue(PartnerProgramProject.objects.filter(pk=self.link.pk).exists())
        self.assertTrue(
            PartnerProgramProject.objects.filter(pk=self.source_link.pk).exists()
        )
        self.assertTrue(
            type(self.member.user).objects.filter(pk=self.member.user_id).exists()
        )
        self.client.force_authenticate(self.member.user)
        self.assertEqual(
            self.client.get(f"/projects/{self.project.pk}/").status_code, 403
        )
        self.assertEqual(self.client.get(f"/projects/{self.source.pk}/").status_code, 200)
        self.assertEqual(
            self.client.get(
                f"/chats/projects/{ProjectChat.objects.get(project=self.project).pk}/"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/chats/projects/{ProjectChat.objects.get(project=self.source).pk}/"
            ).status_code,
            200,
        )

    def test_remaining_registered_team_can_submit_after_removal(self):
        self.assertEqual(self.remove(self.preview()).status_code, 200)
        self.client.force_authenticate(self.leader.user)
        response = self.client.post(
            f"/programs/partner-program-projects/{self.link.pk}/submit/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.link.refresh_from_db()
        self.assertTrue(self.link.submitted)

    def test_existing_minimum_team_size_still_applies(self):
        self.program.legacy_team_min_size = 2
        self.program.save(update_fields=["legacy_team_min_size"])
        self.assertEqual(self.remove(self.preview()).status_code, 200)
        self.client.force_authenticate(self.leader.user)
        response = self.client.post(
            f"/programs/partner-program-projects/{self.link.pk}/submit/"
        )
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "team_min_size")

    def test_submitted_application_scores_and_assignments_are_preserved(self):
        self.link.submitted = True
        self.link.save(update_fields=["submitted"])
        expert = create_rate_expert(program=self.program)
        criterion = Criteria.objects.create(
            partner_program=self.program,
            name="Балл",
            type="int",
            min_value=0,
            max_value=10,
        )
        assignment = ProjectExpertAssignment.objects.create(
            partner_program=self.program, project=self.project, expert=expert.expert
        )
        score = ProjectScore.objects.create(
            project=self.project, criteria=criterion, user=expert, value="7"
        )
        preview = self.preview()
        self.assertTrue(preview["team_changes"][0]["submitted"])
        self.assertEqual(self.remove(preview).status_code, 200)
        self.assertTrue(ProjectScore.objects.filter(pk=score.pk, value="7").exists())
        self.assertTrue(ProjectExpertAssignment.objects.filter(pk=assignment.pk).exists())
        self.link.refresh_from_db()
        self.assertTrue(self.link.submitted)

    def test_changed_team_or_invitation_requires_fresh_preview(self):
        preview = self.preview()
        Invite.objects.filter(pk=self.invite.pk).delete()
        response = self.remove(preview)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(
            Collaborator.objects.filter(
                project=self.project, user=self.member.user
            ).exists()
        )
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=self.member.pk).exists()
        )
        preview = self.preview()
        newcomer = create_program_member(self.program)
        Collaborator.objects.create(project=self.project, user=newcomer.user)
        self.assertEqual(self.remove(preview).status_code, 409)

    def test_shared_link_added_after_preview_aborts_whole_batch(self):
        preview = self.preview()
        PartnerProgramProject.objects.create(
            partner_program=self.foreign, project=self.project
        )
        self.assertEqual(self.remove(preview).status_code, 409)
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=self.member.pk).exists()
        )
        self.assertTrue(
            Collaborator.objects.filter(
                project=self.project, user=self.member.user
            ).exists()
        )

    def test_old_client_and_old_confirmation_cannot_remove_team_members(self):
        preview = self.preview()
        old_client = self.client.post(
            self.root + "remove/",
            {"ids": [self.member.pk], "preview_token": preview["preview_token"]},
            format="json",
        )
        self.assertEqual(old_client.status_code, 400)
        self.assertEqual(self.remove(preview, version=1).status_code, 400)
        old_token = signing.dumps(
            {
                "program": self.program.pk,
                "actor": self.manager.pk,
                "ids": [self.member.pk],
            },
            salt="management-participant-removal-v1",
        )
        self.assertEqual(self.remove({"preview_token": old_token}).status_code, 409)
        self.assertTrue(
            Collaborator.objects.filter(
                project=self.project, user=self.member.user
            ).exists()
        )
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(pk=self.member.pk).exists()
        )

    def test_leader_application_unlinks_even_with_scoped_invites_and_preserves_project(
        self,
    ):
        self.assertEqual(
            self.remove(self.preview([self.leader.pk]), [self.leader.pk]).status_code, 200
        )
        self.assertFalse(PartnerProgramProject.objects.filter(pk=self.link.pk).exists())
        self.assertFalse(Invite.objects.filter(pk=self.invite.pk).exists())
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())
        self.assertTrue(
            Collaborator.objects.filter(
                project=self.source, user=self.member.user
            ).exists()
        )


@override_settings(RUNNING_TESTS=False)
class ApplicationChatRemovalTests(ApplicationTeamFixture, TransactionTestCase):
    def setUp(self):
        self.seed()

    def test_open_socket_cannot_receive_or_type_in_removed_application_but_keeps_source(
        self,
    ):
        from channels.db import database_sync_to_async

        app_chat = ProjectChat.objects.get(project=self.project)
        source_chat = ProjectChat.objects.get(project=self.source)

        async def scenario():
            member = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
            member.scope["user"] = self.member.user
            leader = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
            leader.scope["user"] = self.leader.user
            try:
                self.assertTrue((await member.connect(timeout=5))[0])
                self.assertTrue((await leader.connect(timeout=5))[0])
                await member.receive_json_from(timeout=5)
                preview = await database_sync_to_async(preview_removal)(
                    self.program.pk, self.manager, [self.member.pk]
                )
                await database_sync_to_async(remove_participants)(
                    self.program.pk,
                    self.manager,
                    [self.member.pk],
                    preview["preview_token"],
                )

                def message(chat_id):
                    return {
                        "type": "new_message",
                        "content": {
                            "chat_type": "project",
                            "chat_id": str(chat_id),
                            "text": "Тест",
                            "reply_to": None,
                            "file_urls": [],
                        },
                    }

                await leader.send_json_to(message(app_chat.pk))
                event = await leader.receive_json_from(timeout=5)
                self.assertNotIn("_project_chat_id", event)
                self.assertTrue(await member.receive_nothing(timeout=0.2))
                await member.send_json_to(
                    {
                        "type": "user_typing",
                        "content": {"chat_type": "project", "chat_id": str(app_chat.pk)},
                    }
                )
                self.assertIn("error", await member.receive_json_from(timeout=5))
                self.assertTrue(await leader.receive_nothing(timeout=0.2))
                await leader.send_json_to(message(source_chat.pk))
                await leader.receive_json_from(timeout=5)
                self.assertEqual(
                    (await member.receive_json_from(timeout=5))["content"]["chat_id"],
                    str(source_chat.pk),
                )
            finally:
                import asyncio

                await asyncio.gather(
                    member.disconnect(), leader.disconnect(), return_exceptions=True
                )

        async_to_sync(scenario)()

import json
from pathlib import Path

from django.test import TestCase
from jsonschema import Draft202012Validator

from partner_programs import solution_invitations
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import SolutionInvitation
from partner_programs.tests.test_solution_invitations import InvitationFixture, call


class SolutionInvitationRoleTests(InvitationFixture, TestCase):
    def setUp(self):
        self.seed()

    def state(self):
        self.solution.refresh_from_db()
        return {
            "version": self.solution.version,
            "updated_at": self.solution.updated_at,
            "members": list(self.solution.members.order_by("pk").values()),
            "invitations": list(self.solution.invitations.order_by("pk").values()),
        }

    def create_body(self, **changes):
        return {
            "expected_solution_version": self.solution.version,
            "recipient_user_id": self.recipient.pk,
            **changes,
        }

    def test_create_requires_nonblank_string_role_and_failed_commands_change_nothing(
        self,
    ):
        before = self.state()
        for fields in (
            {},
            {"role": None},
            {"role": ""},
            {"role": " \t\n"},
            {"role": "\u00a0\u2003"},
            {"role": True},
            {"role": 1},
            {"role": []},
            {"role": {}},
            {"role": "Р" * 129},
        ):
            with self.subTest(fields=fields):
                self.assert_error(
                    call(self.captain, "post", self.root, self.create_body(**fields)),
                    400,
                    "validation_error",
                )
                self.assertEqual(self.state(), before)

    def test_create_accepts_one_and_128_characters_without_changing_the_role(self):
        for role in ("Р", "Р" * 128, "  Своя роль  "):
            with self.subTest(length=len(role)):
                recipient = self.registered()
                self.solution.refresh_from_db()
                self.program.legacy_team_max_size = 5
                self.program.save()
                result = call(
                    self.captain,
                    "post",
                    self.root,
                    {**self.create_body(role=role), "recipient_user_id": recipient.pk},
                )
                self.assertEqual(result.status_code, 201, result.data)
                self.assertEqual(result.data["invitation"]["role"], role)
                self.assertEqual(result.data["invitation"]["status"], "pending")
                self.assertEqual(self.solution.members.count(), 1)

    def test_patch_cannot_clear_role_or_change_versions_on_invalid_input(self):
        invitation = self.invite()
        before = self.state()
        url = f"/solution-invitations/{invitation['id']}/"
        for role in (None, "", " \n\t", "\u00a0", True, 123, [], {}, "Р" * 129):
            with self.subTest(role=role):
                self.assert_error(
                    call(
                        self.captain,
                        "patch",
                        url,
                        {
                            "expected_version": invitation["version"],
                            "expected_solution_version": self.solution.version,
                            "role": role,
                        },
                    ),
                    400,
                    "validation_error",
                )
                self.assertEqual(self.state(), before)

    def test_partial_patch_keeps_historical_null_role(self):
        invitation = SolutionInvitation.objects.create(
            solution=self.solution, recipient=self.recipient, role=None
        )
        result = call(
            self.captain,
            "patch",
            f"/solution-invitations/{invitation.pk}/",
            {
                "expected_version": invitation.version,
                "expected_solution_version": self.solution.version,
                "motivational_letter": "Новое сообщение",
            },
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertIsNone(result.data["invitation"]["role"])
        self.assertEqual(
            result.data["invitation"]["motivational_letter"], "Новое сообщение"
        )

    def legacy_invitation(self):
        return SolutionInvitation.objects.create(
            solution=self.solution, recipient=self.recipient, role=None
        )

    def test_historical_null_role_still_reads_and_accepts_without_fabricating_a_role(
        self,
    ):
        invitation = self.legacy_invitation()
        url = f"/solution-invitations/{invitation.pk}/"
        detail = call(self.recipient, "get", url)
        self.assertEqual(detail.status_code, 200, detail.data)
        self.assertIsNone(detail.data["role"])
        accepted = call(self.recipient, "post", url + "accept/", {"expected_version": 1})
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertIsNone(accepted.data["invitation"]["role"])
        self.assertIsNone(self.solution.members.get(user=self.recipient).role)

    def test_historical_null_role_can_be_declined(self):
        invitation = self.legacy_invitation()
        result = call(
            self.recipient,
            "post",
            f"/solution-invitations/{invitation.pk}/decline/",
            {"expected_version": 1},
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["invitation"]["status"], "declined")
        self.assertIsNone(result.data["invitation"]["role"])

    def test_historical_null_role_can_be_revoked(self):
        invitation = self.legacy_invitation()
        result = call(
            self.captain,
            "delete",
            f"/solution-invitations/{invitation.pk}/?expected_version=1&expected_solution_version=1",
        )
        self.assertEqual(result.status_code, 204)
        self.assertFalse(SolutionInvitation.objects.filter(pk=invitation.pk).exists())
        self.assertEqual(self.solution.members.count(), 1)

    def test_direct_service_creation_cannot_bypass_required_role(self):
        before = self.state()
        for fields in (
            {},
            {"role": None},
            {"role": " "},
            {"role": 123},
            {"role": "Р" * 129},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(SolutionError) as error:
                    solution_invitations.create_invitation(
                        program_id=self.program.pk,
                        solution_id=self.solution.pk,
                        actor=self.captain,
                        **self.create_body(**fields),
                    )
                self.assertEqual(error.exception.status_code, 400)
                self.assertEqual(str(error.exception.get_codes()), "validation_error")
                self.assertEqual(self.state(), before)

    def test_direct_service_patch_cannot_bypass_role_validation(self):
        invitation = self.invite()
        before = self.state()
        with self.assertRaises(SolutionError) as error:
            solution_invitations.update_invitation(
                invitation_id=invitation["id"],
                actor=self.captain,
                expected_version=1,
                expected_solution_version=self.solution.version,
                role=None,
            )
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.state(), before)

    def test_c00_matches_invalid_and_partial_role_requests(self):
        spec = json.loads(
            (
                Path(__file__).parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        schema = spec["components"]["schemas"]
        create = Draft202012Validator(schema["CreateInvitation"])
        for fields in (
            {},
            {"role": None},
            {"role": ""},
            {"role": " \t"},
            {"role": "Р" * 129},
        ):
            self.assertFalse(create.is_valid(self.create_body(**fields)))
        for role in ("Р", "Р" * 128):
            self.assertTrue(create.is_valid(self.create_body(role=role)))
        patch = Draft202012Validator(schema["UpdateInvitation"])
        version = {"expected_version": 1, "expected_solution_version": 1}
        self.assertTrue(patch.is_valid({**version, "motivational_letter": "Текст"}))
        self.assertFalse(patch.is_valid({**version, "role": None}))

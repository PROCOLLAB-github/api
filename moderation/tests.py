from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from moderation.models import ModerationLog
from moderation.tasks import freeze_stale_programs
from moderation.views import (
    ModerationDecisionView,
    ModerationProgramArchiveView,
    ModerationProgramDetailView,
    ModerationProgramFreezeView,
    ModerationProgramListView,
    ModerationProgramRestoreView,
    RejectionReasonListView,
)
from partner_programs.models import PartnerProgram, PartnerProgramMaterial
from partner_programs.views import PartnerProgramDetail


@override_settings(FRONTEND_URL="https://app.test", DEFAULT_FROM_EMAIL="from@test")
class ModerationProgramTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.list_view = ModerationProgramListView.as_view()
        self.detail_view = ModerationProgramDetailView.as_view()
        self.decision_view = ModerationDecisionView.as_view()
        self.freeze_view = ModerationProgramFreezeView.as_view()
        self.restore_view = ModerationProgramRestoreView.as_view()
        self.archive_view = ModerationProgramArchiveView.as_view()
        self.reasons_view = RejectionReasonListView.as_view()
        self.public_detail_view = PartnerProgramDetail.as_view()
        self.now = timezone.now()

        self.admin = self.create_user("admin-moderation@example.com", is_staff=True)
        self.manager = self.create_user("manager-moderation@example.com")
        self.outsider = self.create_user("outsider-moderation@example.com")

    def create_user(self, email: str, **extra_fields):
        return get_user_model().objects.create_user(
            email=email,
            password="pass",
            first_name="Test",
            last_name="User",
            birthday="1990-01-01",
            **extra_fields,
        )

    def create_program(self, **overrides):
        defaults = {
            "name": "Moderation program",
            "tag": "moderation_program",
            "description": (
                "Program description for moderation readiness. "
                "This text is intentionally long enough to satisfy the current "
                "public information checks before a championship can be submitted."
            ),
            "city": "Moscow",
            "data_schema": {"fields": [{"name": "participant_name"}]},
            "status": PartnerProgram.STATUS_PENDING_MODERATION,
            "cover_image_address": "https://example.com/program-cover.jpg",
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now + timezone.timedelta(days=20),
            "datetime_finished": self.now + timezone.timedelta(days=50),
        }
        defaults.update(overrides)
        program = PartnerProgram.objects.create(**defaults)
        program.managers.add(self.manager)
        return program

    def create_material(self, program):
        return PartnerProgramMaterial.objects.create(
            program=program,
            title="Material",
            url="https://example.com/material.pdf",
        )

    def test_staff_can_list_programs_on_moderation(self):
        program = self.create_program()

        request = self.factory.get("/api/admin/moderation/programs/")
        force_authenticate(request, user=self.admin)
        response = self.list_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], program.id)

    def test_non_staff_cannot_use_admin_moderation_endpoint(self):
        self.create_program()

        request = self.factory.get("/api/admin/moderation/programs/")
        force_authenticate(request, user=self.manager)
        response = self.list_view(request)

        self.assertEqual(response.status_code, 403)

    def test_staff_gets_russian_rejection_reasons(self):
        request = self.factory.get("/api/admin/moderation/rejection-reasons/")
        force_authenticate(request, user=self.admin)
        response = self.reasons_view(request)

        self.assertEqual(response.status_code, 200)
        labels_by_code = {reason["code"]: reason["label"] for reason in response.data}
        self.assertEqual(
            labels_by_code[ModerationLog.REJECTION_REASON_INSUFFICIENT_DATA],
            "Недостаточно данных",
        )
        self.assertEqual(
            labels_by_code[ModerationLog.REJECTION_REASON_PLATFORM_RULES],
            "Нарушение правил платформы",
        )

    def test_staff_can_get_program_detail_with_history(self):
        program = self.create_program()
        self.create_material(program)
        ModerationLog.objects.create(
            program=program,
            author=self.manager,
            action=ModerationLog.ACTION_SUBMITTED,
            status_before=PartnerProgram.STATUS_DRAFT,
            status_after=PartnerProgram.STATUS_PENDING_MODERATION,
        )

        request = self.factory.get(f"/api/admin/moderation/programs/{program.id}/")
        force_authenticate(request, user=self.admin)
        response = self.detail_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], program.id)
        self.assertEqual(len(response.data["materials"]), 1)
        self.assertEqual(len(response.data["moderation_history"]), 1)

    @patch("moderation.services.notify_program_moderation_approved", return_value=1)
    def test_staff_can_approve_program(self, notify_mock):
        program = self.create_program()

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/decision/",
            {"decision": "approve"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.decision_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_PUBLISHED)
        self.assertFalse(program.draft)
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_APPROVED,
                author=self.admin,
            ).exists()
        )
        self.assertEqual(notify_mock.call_count, 1)

    def test_staff_cannot_reject_without_comment(self):
        program = self.create_program()

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/decision/",
            {
                "decision": "reject",
                "reason_code": ModerationLog.REJECTION_REASON_OTHER,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.decision_view(request, pk=program.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("comment", response.data)

    @patch("moderation.services.notify_program_moderation_rejected", return_value=1)
    def test_staff_can_reject_program_with_sections_to_fix(self, notify_mock):
        program = self.create_program()

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/decision/",
            {
                "decision": "reject",
                "comment": "Please clarify rules and dates.",
                "reason_code": ModerationLog.REJECTION_REASON_INSUFFICIENT_DATA,
                "sections_to_fix": ["basic_info", "dates"],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.decision_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_REJECTED)
        log = ModerationLog.objects.get(program=program)
        self.assertEqual(log.action, ModerationLog.ACTION_REJECTED)
        self.assertEqual(log.sections_to_fix, ["basic_info", "dates"])
        self.assertEqual(notify_mock.call_count, 1)

    @patch("moderation.services.notify_program_moderation_rejected", return_value=1)
    def test_manager_can_see_active_rejection_result(self, notify_mock):
        program = self.create_program()
        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/decision/",
            {
                "decision": "reject",
                "comment": "Please clarify rules and dates.",
                "reason_code": ModerationLog.REJECTION_REASON_INSUFFICIENT_DATA,
                "sections_to_fix": ["basic_info", "dates"],
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.decision_view(request, pk=program.id)
        self.assertEqual(response.status_code, 200)

        detail_request = self.factory.get(f"/programs/{program.id}/")
        force_authenticate(detail_request, user=self.manager)
        detail_response = self.public_detail_view(detail_request, pk=program.id)

        self.assertEqual(detail_response.status_code, 200)
        result = detail_response.data["moderation_result"]
        self.assertEqual(
            result["rejection_reason_code"],
            ModerationLog.REJECTION_REASON_INSUFFICIENT_DATA,
        )
        self.assertEqual(result["sections_to_fix"], ["basic_info", "dates"])
        self.assertEqual(result["rejected_by"]["id"], self.admin.id)
        self.assertEqual(notify_mock.call_count, 1)

    def test_decision_for_non_pending_program_returns_409(self):
        program = self.create_program(status=PartnerProgram.STATUS_DRAFT)

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/decision/",
            {"decision": "approve"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.decision_view(request, pk=program.id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["current_status"], PartnerProgram.STATUS_DRAFT)

    @patch("moderation.services.send_mail", return_value=1)
    def test_staff_can_manually_freeze_published_program(self, send_mail_mock):
        program = self.create_program(status=PartnerProgram.STATUS_PUBLISHED)

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/freeze/",
            {"comment": "Temporary pause"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.freeze_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_FROZEN)
        self.assertIsNotNone(program.frozen_at)
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_FREEZE,
                author=self.admin,
            ).exists()
        )
        self.assertEqual(send_mail_mock.call_count, 2)

    def test_manual_freeze_requires_comment(self):
        program = self.create_program(status=PartnerProgram.STATUS_PUBLISHED)

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/freeze/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.freeze_view(request, pk=program.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("comment", response.data)

    @patch("moderation.services.send_mail", return_value=1)
    def test_staff_can_restore_frozen_program_after_material_upload(
        self,
        send_mail_mock,
    ):
        program = self.create_program(
            status=PartnerProgram.STATUS_FROZEN,
            frozen_at=self.now - timezone.timedelta(days=1),
        )
        self.create_material(program)

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/restore/",
            {"comment": "Materials uploaded"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.restore_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_PUBLISHED)
        self.assertIsNone(program.frozen_at)
        self.assertEqual(send_mail_mock.call_count, 1)

    def test_restore_frozen_program_requires_materials(self):
        program = self.create_program(
            status=PartnerProgram.STATUS_FROZEN,
            frozen_at=self.now - timezone.timedelta(days=1),
        )

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/restore/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.restore_view(request, pk=program.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("materials", response.data)

    @patch("moderation.services.send_mail", return_value=1)
    def test_staff_can_archive_frozen_program_with_comment(self, send_mail_mock):
        program = self.create_program(
            status=PartnerProgram.STATUS_FROZEN,
            frozen_at=self.now - timezone.timedelta(days=1),
        )

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/archive/",
            {"comment": "Archive stale program"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.archive_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_ARCHIVED)
        self.assertEqual(send_mail_mock.call_count, 1)

    def test_archive_draft_program_returns_409(self):
        program = self.create_program(status=PartnerProgram.STATUS_DRAFT)

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/archive/",
            {},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.archive_view(request, pk=program.id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["current_status"], PartnerProgram.STATUS_DRAFT)

    @patch("moderation.services.send_mail", return_value=1)
    def test_task_auto_freezes_stale_published_program_without_materials(
        self,
        send_mail_mock,
    ):
        program = self.create_program(
            status=PartnerProgram.STATUS_PUBLISHED,
            datetime_started=self.now - timezone.timedelta(days=4),
        )

        result = freeze_stale_programs()

        self.assertEqual(result["frozen_count"], 1)
        self.assertEqual(result["frozen_ids"], [program.id])
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_FROZEN)
        self.assertEqual(send_mail_mock.call_count, 2)

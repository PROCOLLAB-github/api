from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from moderation.models import ModerationLog
from partner_programs.models import (
    LegalDocument,
    PartnerProgram,
    PartnerProgramLegalSettings,
    PartnerProgramMaterial,
)
from project_rates.models import Criteria

User = get_user_model()


class ProgramEditReadinessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = timezone.now()
        self.manager = User.objects.create_user(
            email="manager-readiness@example.com",
            password="pass",
            first_name="Manager",
            last_name="Readiness",
            birthday="1990-01-01",
            is_active=True,
        )
        self.expert_user = User.objects.create_user(
            email="expert-readiness@example.com",
            password="pass",
            first_name="Expert",
            last_name="Readiness",
            birthday="1991-01-01",
            user_type=User.EXPERT,
            is_active=True,
        )
        self.ensure_legal_documents()

    def ensure_legal_documents(self):
        for doc_type in (
            LegalDocument.TYPE_PRIVACY_POLICY,
            LegalDocument.TYPE_PARTICIPANT_CONSENT,
            LegalDocument.TYPE_PARTICIPATION_TERMS,
            LegalDocument.TYPE_ORGANIZER_TERMS,
        ):
            LegalDocument.objects.get_or_create(
                type=doc_type,
                version="test",
                is_active=True,
                defaults={
                    "title": doc_type,
                    "content_html": f"<p>{doc_type}</p>",
                },
            )

    def create_program(self, **overrides):
        defaults = {
            "name": "Case Championship",
            "tag": "case_championship",
            "description": "Описание чемпионата " * 14,
            "city": "Москва",
            "data_schema": {"fio": {"type": "text", "label": "ФИО"}},
            "draft": True,
            "status": PartnerProgram.STATUS_DRAFT,
            "is_competitive": False,
            "datetime_started": self.now + timezone.timedelta(days=1),
            "datetime_registration_ends": self.now + timezone.timedelta(days=3),
            "datetime_project_submission_ends": self.now + timezone.timedelta(days=5),
            "datetime_evaluation_ends": self.now + timezone.timedelta(days=6),
            "datetime_finished": self.now + timezone.timedelta(days=7),
        }
        defaults.update(overrides)
        program = PartnerProgram.objects.create(**defaults)
        program.managers.add(self.manager)
        PartnerProgramLegalSettings.objects.update_or_create(
            program=program,
            defaults={
                "organizer_terms_accepted_by": self.manager,
                "organizer_terms_accepted_at": self.now,
                "organizer_terms_version": "test",
            },
        )
        return program

    def test_non_competitive_program_can_submit_without_operational_materials(self):
        program = self.create_program()
        self.client.force_authenticate(self.manager)

        response = self.client.get(f"/programs/{program.id}/readiness/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["checklist"]["criteria_experts"], "not_applicable")
        self.assertNotIn("criteria_experts", response.data["missing_required_sections"])
        self.assertNotIn("materials", response.data["missing_required_sections"])
        self.assertIn(
            "materials",
            response.data["operational_readiness"]["missing_required_sections"],
        )
        self.assertTrue(response.data["can_submit_to_moderation"])

        submit_response = self.client.post(
            f"/programs/{program.id}/submit-to-moderation/"
        )

        self.assertEqual(submit_response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_PENDING_MODERATION)
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_SUBMITTED,
            ).exists()
        )

    def test_competitive_criteria_and_experts_are_operational_readiness(self):
        program = self.create_program(is_competitive=True)
        self.client.force_authenticate(self.manager)

        response = self.client.get(f"/programs/{program.id}/readiness/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["checklist"]["criteria_experts"])
        self.assertNotIn("criteria_experts", response.data["missing_required_sections"])
        self.assertIn(
            "criteria_experts",
            response.data["operational_readiness"]["missing_required_sections"],
        )

        Criteria.objects.create(
            partner_program=program,
            name="Impact",
            description="Impact",
            type="int",
            min_value=1,
            max_value=10,
            weight=60,
        )
        Criteria.objects.create(
            partner_program=program,
            name="Realism",
            description="Realism",
            type="int",
            min_value=1,
            max_value=10,
            weight=40,
        )
        self.expert_user.expert.programs.add(program)

        response = self.client.get(f"/programs/{program.id}/readiness/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["checklist"]["criteria_experts"])
        self.assertNotIn(
            "criteria_experts",
            response.data["operational_readiness"]["missing_required_sections"],
        )

    def test_submit_blocks_when_required_readiness_is_missing(self):
        program = self.create_program(description="short")
        self.client.force_authenticate(self.manager)

        response = self.client.post(f"/programs/{program.id}/submit-to-moderation/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("basic_info", response.data["errors"])
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_DRAFT)

    def test_withdraw_from_moderation_returns_program_to_draft(self):
        program = self.create_program(status=PartnerProgram.STATUS_PENDING_MODERATION)
        self.client.force_authenticate(self.manager)

        response = self.client.post(f"/programs/{program.id}/withdraw-from-moderation/")

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(program.status, PartnerProgram.STATUS_DRAFT)
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_WITHDRAWN,
            ).exists()
        )

    def test_published_program_registration_status_gate_remains_open(self):
        program = self.create_program(status=PartnerProgram.STATUS_DRAFT)
        self.client.force_authenticate(self.manager)

        response = self.client.post(f"/programs/{program.id}/register/", {})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["current_status"], PartnerProgram.STATUS_DRAFT)

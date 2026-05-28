from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from files.models import UserFile
from moderation.models import ModerationLog
from moderation.views import (
    ModerationVerificationDecisionView,
    ModerationVerificationRequestListView,
    ModerationVerificationRevokeView,
    VerificationRejectionReasonListView,
)
from partner_programs.models import PartnerProgram, PartnerProgramVerificationRequest
from partner_programs.views import (
    CompanySearchView,
    PartnerProgramList,
    PartnerProgramVerificationStatusView,
    PartnerProgramVerificationSubmitView,
)
from projects.models import Company


@override_settings(FRONTEND_URL="https://app.test", DEFAULT_FROM_EMAIL="from@test")
class PartnerProgramVerificationTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.submit_view = PartnerProgramVerificationSubmitView.as_view()
        self.status_view = PartnerProgramVerificationStatusView.as_view()
        self.company_search_view = CompanySearchView.as_view()
        self.admin_list_view = ModerationVerificationRequestListView.as_view()
        self.admin_decision_view = ModerationVerificationDecisionView.as_view()
        self.admin_revoke_view = ModerationVerificationRevokeView.as_view()
        self.admin_reasons_view = VerificationRejectionReasonListView.as_view()
        self.public_list_view = PartnerProgramList.as_view()
        self.now = timezone.now()
        self.file_index = 0

        self.admin = self.create_user("admin-verification@example.com", is_staff=True)
        self.manager = self.create_user("manager-verification@example.com")
        self.outsider = self.create_user("outsider-verification@example.com")

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
            "name": "Verification program",
            "tag": "verification_program",
            "description": "Program description",
            "city": "Moscow",
            "data_schema": {},
            "status": PartnerProgram.STATUS_PUBLISHED,
            "verification_status": PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
            "projects_availability": "all_users",
            "datetime_registration_ends": self.now + timezone.timedelta(days=10),
            "datetime_started": self.now + timezone.timedelta(days=20),
            "datetime_finished": self.now + timezone.timedelta(days=50),
        }
        defaults.update(overrides)
        program = PartnerProgram.objects.create(**defaults)
        program.managers.add(self.manager)
        return program

    def create_company(self, **overrides):
        defaults = {
            "name": "Official Company",
            "inn": "7707083893",
        }
        defaults.update(overrides)
        return Company.objects.create(**defaults)

    def create_document(self, index=None, **overrides):
        if index is None:
            self.file_index += 1
            index = self.file_index
        defaults = {
            "link": f"https://cdn.test/verification-doc-{index}.pdf",
            "user": self.manager,
            "name": f"verification-doc-{index}",
            "extension": "pdf",
            "mime_type": "application/pdf",
            "size": 1024,
        }
        defaults.update(overrides)
        return UserFile.objects.create(**defaults)

    def valid_payload(self, **overrides):
        documents = overrides.pop("documents", None)
        if documents is None:
            document = self.create_document()
            documents = [document.link]
        payload = {
            "company_name": "Official Company",
            "inn": "7707083893",
            "legal_name": 'OOO "Official Company"',
            "ogrn": "1027700132195",
            "website": "https://official.example.com",
            "region": "Moscow",
            "contact_full_name": "Ivan Manager",
            "contact_position": "Program lead",
            "contact_email": "lead@example.com",
            "contact_phone": "+79990000000",
            "company_role_description": "Company organizes the championship.",
            "documents": documents,
        }
        payload.update(overrides)
        return payload

    def test_manager_can_submit_verification_request(self):
        program = self.create_program()
        other_program = self.create_program(
            name="Second managed program",
            tag="second_managed_program",
        )

        request = self.factory.post(
            f"/programs/{program.id}/verification/submit/",
            self.valid_payload(),
            format="json",
        )
        force_authenticate(request, user=self.manager)
        response = self.submit_view(request, pk=program.id)

        self.assertEqual(response.status_code, 201)
        program.refresh_from_db()
        self.assertEqual(
            program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_PENDING,
        )
        verification_request = PartnerProgramVerificationRequest.objects.get(
            program=program
        )
        self.assertEqual(
            verification_request.status,
            PartnerProgramVerificationRequest.STATUS_PENDING,
        )
        self.assertEqual(verification_request.company_name, "Official Company")
        self.assertEqual(verification_request.inn, "7707083893")
        self.assertEqual(verification_request.website, "https://official.example.com")
        self.assertEqual(verification_request.documents.count(), 1)
        self.assertEqual(program.company_id, verification_request.company_id)
        other_program.refresh_from_db()
        self.assertEqual(
            other_program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_PENDING,
        )
        self.assertEqual(other_program.company_id, verification_request.company_id)
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_VERIFICATION_SUBMITTED,
                author=self.manager,
                status_before=PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
                status_after=PartnerProgram.VERIFICATION_STATUS_PENDING,
            ).exists()
        )
        request = self.factory.get(f"/programs/{other_program.id}/verification/")
        force_authenticate(request, user=self.manager)
        response = self.status_view(request, pk=other_program.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["verification_status"],
            PartnerProgram.VERIFICATION_STATUS_PENDING,
        )
        self.assertEqual(response.data["latest_request"]["id"], verification_request.id)

    def test_submit_without_required_fields_returns_400(self):
        program = self.create_program()

        request = self.factory.post(
            f"/programs/{program.id}/verification/submit/",
            {"company_name": "Official Company", "inn": "7707083893"},
            format="json",
        )
        force_authenticate(request, user=self.manager)
        response = self.submit_view(request, pk=program.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("contact_full_name", response.data)

    def test_submit_with_invalid_inn_returns_400(self):
        program = self.create_program()
        payload = self.valid_payload(
            company_name="Invalid Company",
            inn="123",
        )

        request = self.factory.post(
            f"/programs/{program.id}/verification/submit/",
            payload,
            format="json",
        )
        force_authenticate(request, user=self.manager)
        response = self.submit_view(request, pk=program.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("inn", response.data)

    def test_submit_without_documents_returns_400(self):
        program = self.create_program()
        payload = self.valid_payload(documents=[])

        request = self.factory.post(
            f"/programs/{program.id}/verification/submit/",
            payload,
            format="json",
        )
        force_authenticate(request, user=self.manager)
        response = self.submit_view(request, pk=program.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("documents", response.data)

    def test_submit_pending_or_verified_program_returns_409(self):
        for status_value in (
            PartnerProgram.VERIFICATION_STATUS_PENDING,
            PartnerProgram.VERIFICATION_STATUS_VERIFIED,
        ):
            program = self.create_program(
                verification_status=status_value,
                tag=f"program_{status_value}",
            )
            request = self.factory.post(
                f"/programs/{program.id}/verification/submit/",
                self.valid_payload(),
                format="json",
            )
            force_authenticate(request, user=self.manager)
            response = self.submit_view(request, pk=program.id)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["current_status"], status_value)

    def test_admin_can_approve_verification_request(self):
        program, verification_request, company = self.create_pending_request()
        other_program = self.create_program(
            name="Other managed program",
            tag="other_managed_program",
            status=PartnerProgram.STATUS_DRAFT,
        )

        request = self.factory.post(
            f"/api/admin/moderation/verification-requests/{verification_request.id}/decision/",
            {"decision": "approve", "comment": "Looks valid"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.admin_decision_view(request, pk=verification_request.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        verification_request.refresh_from_db()
        self.assertEqual(
            program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_VERIFIED,
        )
        self.assertEqual(program.status, PartnerProgram.STATUS_PUBLISHED)
        self.assertEqual(program.company_id, company.id)
        other_program.refresh_from_db()
        self.assertEqual(
            other_program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_VERIFIED,
        )
        self.assertEqual(other_program.status, PartnerProgram.STATUS_DRAFT)
        self.assertEqual(other_program.company_id, company.id)
        self.assertEqual(
            verification_request.status,
            PartnerProgramVerificationRequest.STATUS_APPROVED,
        )
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_VERIFICATION_APPROVE,
                author=self.admin,
            ).exists()
        )
    def test_admin_cannot_reject_without_comment(self):
        _, verification_request, _ = self.create_pending_request()

        request = self.factory.post(
            f"/api/admin/moderation/verification-requests/{verification_request.id}/decision/",
            {
                "decision": "reject",
                "rejection_reason": PartnerProgramVerificationRequest.REJECTION_OTHER,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.admin_decision_view(request, pk=verification_request.id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("comment", response.data)

    def test_admin_can_reject_verification_request(self):
        program, verification_request, _ = self.create_pending_request()
        other_program = self.create_program(
            name="Other rejected profile program",
            tag="other_rejected_profile_program",
            status=PartnerProgram.STATUS_DRAFT,
        )

        request = self.factory.post(
            f"/api/admin/moderation/verification-requests/{verification_request.id}/decision/",
            {
                "decision": "reject",
                "comment": "Documents are not enough",
                "reason_code": PartnerProgramVerificationRequest.REJECTION_INSUFFICIENT_DOCUMENTS,
            },
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.admin_decision_view(request, pk=verification_request.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        verification_request.refresh_from_db()
        self.assertEqual(
            program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_REJECTED,
        )
        self.assertEqual(program.status, PartnerProgram.STATUS_PUBLISHED)
        other_program.refresh_from_db()
        self.assertEqual(
            other_program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_REJECTED,
        )
        self.assertEqual(other_program.status, PartnerProgram.STATUS_DRAFT)
        self.assertEqual(
            verification_request.status,
            PartnerProgramVerificationRequest.STATUS_REJECTED,
        )
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_VERIFICATION_REJECT,
                author=self.admin,
            ).exists()
        )
    def test_admin_can_revoke_verified_program(self):
        program, _, company = self.create_pending_request()
        program.verification_status = PartnerProgram.VERIFICATION_STATUS_VERIFIED
        program.company = company
        program.save()

        request = self.factory.post(
            f"/api/admin/moderation/programs/{program.id}/verification/revoke/",
            {"comment": "Verification is no longer valid"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.admin_revoke_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        program.refresh_from_db()
        self.assertEqual(
            program.verification_status,
            PartnerProgram.VERIFICATION_STATUS_REVOKED,
        )
        self.assertEqual(program.company_id, company.id)
        self.assertTrue(
            ModerationLog.objects.filter(
                program=program,
                action=ModerationLog.ACTION_VERIFICATION_REVOKE,
                author=self.admin,
            ).exists()
        )
    def test_non_admin_cannot_get_verification_request_list(self):
        request = self.factory.get("/api/admin/moderation/verification-requests/")
        force_authenticate(request, user=self.manager)
        response = self.admin_list_view(request)

        self.assertEqual(response.status_code, 403)

    def test_admin_can_get_verification_rejection_reasons(self):
        request = self.factory.get("/api/admin/moderation/verification/rejection-reasons/")
        force_authenticate(request, user=self.admin)
        response = self.admin_reasons_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data), 1)
        reason_codes = {reason["code"] for reason in response.data}
        self.assertIn(
            PartnerProgramVerificationRequest.REJECTION_INSUFFICIENT_DOCUMENTS,
            reason_codes,
        )
        self.assertTrue(all(reason.get("label") for reason in response.data))
        labels_by_code = {reason["code"]: reason["label"] for reason in response.data}
        self.assertEqual(
            labels_by_code[PartnerProgramVerificationRequest.REJECTION_INSUFFICIENT_DOCUMENTS],
            "Недостаточно документов",
        )

    def test_admin_can_filter_and_search_verification_requests(self):
        program, verification_request, _ = self.create_pending_request()
        self.create_pending_request(
            program_overrides={
                "name": "Another program",
                "tag": "another_program",
            },
            company_overrides={"name": "Another Company", "inn": "500100732259"},
        )

        request = self.factory.get(
            "/api/admin/moderation/verification-requests/?status=pending&search=Official"
        )
        force_authenticate(request, user=self.admin)
        response = self.admin_list_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], verification_request.id)
        self.assertEqual(response.data["results"][0]["program"]["id"], program.id)

    def test_organizer_can_view_verification_status_history(self):
        program, verification_request, _ = self.create_pending_request()

        request = self.factory.get(f"/programs/{program.id}/verification/")
        force_authenticate(request, user=self.manager)
        response = self.status_view(request, pk=program.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["current_status"],
            PartnerProgram.VERIFICATION_STATUS_PENDING,
        )
        self.assertFalse(response.data["is_verified"])
        self.assertEqual(response.data["latest_request"]["id"], verification_request.id)
        self.assertEqual(len(response.data["history"]), 1)
        self.assertEqual(len(response.data["requests_history"]), 1)

    def test_resubmission_creates_new_request_and_keeps_history(self):
        program, first_request, _ = self.create_pending_request()
        first_request.status = PartnerProgramVerificationRequest.STATUS_REJECTED
        first_request.decided_at = timezone.now()
        first_request.decided_by = self.admin
        first_request.admin_comment = "Rejected once"
        first_request.rejection_reason = (
            PartnerProgramVerificationRequest.REJECTION_INSUFFICIENT_DOCUMENTS
        )
        first_request.save()
        program.verification_status = PartnerProgram.VERIFICATION_STATUS_REJECTED
        program.save(update_fields=["verification_status"])

        request = self.factory.post(
            f"/programs/{program.id}/verification/submit/",
            self.valid_payload(company_name="Second Company", inn="500100732259"),
            format="json",
        )
        force_authenticate(request, user=self.manager)
        response = self.submit_view(request, pk=program.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(program.verification_requests.count(), 2)
        self.assertEqual(
            response.data["verification_status"],
            PartnerProgram.VERIFICATION_STATUS_PENDING,
        )
        self.assertEqual(response.data["latest_request"]["company_name"], "Second Company")
        self.assertEqual(len(response.data["requests_history"]), 2)

    def test_decision_is_allowed_only_for_pending_requests(self):
        _, verification_request, _ = self.create_pending_request()
        verification_request.status = PartnerProgramVerificationRequest.STATUS_APPROVED
        verification_request.decided_at = timezone.now()
        verification_request.save()

        request = self.factory.post(
            f"/api/admin/moderation/verification/{verification_request.id}/decision/",
            {"decision": "approve"},
            format="json",
        )
        force_authenticate(request, user=self.admin)
        response = self.admin_decision_view(request, pk=verification_request.id)

        self.assertEqual(response.status_code, 409)

    def test_public_list_serializer_marks_verified_program_and_filters(self):
        verified = self.create_program(
            name="Verified program",
            tag="verified_program",
            verification_status=PartnerProgram.VERIFICATION_STATUS_VERIFIED,
        )
        company = self.create_company()
        approved_request = PartnerProgramVerificationRequest.objects.create(
            program=verified,
            company=company,
            company_name="Approved Snapshot LLC",
            inn=company.inn,
            initiator=self.manager,
            contact_full_name="Ivan Manager",
            contact_position="Program lead",
            contact_email="lead@example.com",
            contact_phone="+79990000000",
            company_role_description="Company organizes the championship.",
            status=PartnerProgramVerificationRequest.STATUS_APPROVED,
            decided_at=timezone.now(),
            decided_by=self.admin,
        )
        self.create_program(
            name="Plain program",
            tag="plain_program",
            verification_status=PartnerProgram.VERIFICATION_STATUS_NOT_REQUESTED,
        )

        request = self.factory.get("/programs/?verified_only=true")
        response = self.public_list_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        result = response.data["results"][0]
        self.assertEqual(result["id"], verified.id)
        self.assertTrue(result["is_verified"])
        self.assertEqual(result["verified_company_name"], approved_request.company_name)

        company.name = "Changed Company Name"
        company.save(update_fields=["name"])
        request = self.factory.get("/programs/?verified_only=true")
        response = self.public_list_view(request)
        self.assertEqual(
            response.data["results"][0]["verified_company_name"],
            "Approved Snapshot LLC",
        )

    def test_company_search_matches_name_and_inn(self):
        company = self.create_company(name="Searchable Company", inn="7707083893")
        self.create_company(name="Other Company", inn="500100732259")

        request = self.factory.get("/api/companies/search/?query=770708")
        force_authenticate(request, user=self.manager)
        response = self.company_search_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], company.id)

    def create_pending_request(self, program_overrides=None, company_overrides=None):
        program_overrides = program_overrides or {}
        company_overrides = company_overrides or {}
        program = self.create_program(
            verification_status=PartnerProgram.VERIFICATION_STATUS_PENDING,
            **program_overrides,
        )
        company = self.create_company(**company_overrides)
        verification_request = PartnerProgramVerificationRequest.objects.create(
            program=program,
            company=company,
            company_name=company.name,
            inn=company.inn,
            legal_name=company.name,
            ogrn="1027700132195",
            website="https://official.example.com",
            region="Moscow",
            initiator=self.manager,
            contact_full_name="Ivan Manager",
            contact_position="Program lead",
            contact_email="lead@example.com",
            contact_phone="+79990000000",
            company_role_description="Company organizes the championship.",
        )
        verification_request.documents.add(self.create_document())
        return program, verification_request, company

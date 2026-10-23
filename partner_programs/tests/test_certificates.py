import io
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings, tag
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from partner_programs.certificate_models import (
    ProgramCertificate,
    ProgramCertificateBatch,
)
from partner_programs.services import certificates as service
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
    create_user,
)
from projects.models import Collaborator


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CertificateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = create_user(first_name="Ирина", last_name="Орлова")
        cls.other = create_user()
        cls.program = create_partner_program(is_competitive=True)
        cls.program.managers.add(cls.manager)
        cls.leader = create_user(first_name="Анна", last_name="Крылова")
        cls.member = create_user()
        cls.only_registered = create_user()
        for user in (cls.leader, cls.member, cls.only_registered):
            create_program_member(cls.program, user=user)
        project = create_project(leader=cls.leader)
        create_program_project(cls.program, project=project, submitted=True)
        Collaborator.objects.bulk_create([Collaborator(project=project, user=cls.member)])
        # A profile project reference alone does not prove submitted team membership.
        cls.only_registered.partner_program_profiles.filter(
            partner_program=cls.program
        ).update(project=project)
        cls.foreign = create_partner_program(is_competitive=True)
        create_program_project(
            cls.foreign,
            project=create_project(leader=cls.only_registered),
            submitted=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.root = f"/programs/{self.program.pk}/management/certificates/"
        self.config = service.config_for(self.program)

    def batch(self, **overrides):
        data = {
            "program": self.program,
            "snapshot": self.config.draft,
            "issue_at": timezone.now(),
            "public_base_url": "https://dev.procollab.ru",
        }
        data.update(overrides)
        return ProgramCertificateBatch.objects.create(**data)

    def row(self, **overrides):
        data = {
            "program": self.program,
            "batch": self.batch(),
            "user": self.leader,
            "name": "Анна Крылова",
            "email": self.leader.email,
        }
        data.update(overrides)
        return ProgramCertificate.objects.create(**data)

    def image(self, kind="PNG"):
        buffer = io.BytesIO()
        Image.new("RGBA" if kind == "PNG" else "RGB", (120, 60)).save(buffer, format=kind)
        return SimpleUploadedFile(
            "signature.png", buffer.getvalue(), content_type="image/png"
        )

    def test_access_requires_program_manager_and_does_not_leak_email(self):
        for user, status in [
            (None, 401),
            (self.other, 403),
            (self.member, 403),
            (self.manager, 200),
        ]:
            self.client.force_authenticate(user)
            for path in ("", "deliveries/", "archive/"):
                self.assertEqual(self.client.get(self.root + path).status_code, status)
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.post(self.root + "activate/", {"revision": 1}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                self.root + "assets/", {"kind": "signature", "file": self.image()}
            ).status_code,
            403,
        )

    def test_exact_two_audiences_deduplicate_and_scope_actual_team(self):
        self.assertEqual(
            set(service.recipient_users(self.program, "submitted")),
            {self.leader, self.member},
        )
        self.assertEqual(
            set(service.recipient_users(self.program, "all")),
            {self.leader, self.member, self.only_registered},
        )
        state = self.client.get(self.root).data
        self.assertEqual(state["eligible_counts"], {"all": 3, "submitted": 2})
        self.assertEqual(state["draft"]["director"], "")

    def test_revision_conflict_and_geometry_validation(self):
        draft = service.default_draft()
        response = self.client.put(
            self.root, {"revision": 1, "draft": draft}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self.client.put(
                self.root, {"revision": 1, "draft": draft}, format="json"
            ).status_code,
            409,
        )
        draft["layout"]["name"]["x"] = 90
        self.assertEqual(
            self.client.put(
                self.root, {"revision": 2, "draft": draft}, format="json"
            ).status_code,
            400,
        )

    def test_foreign_assets_and_arbitrary_template_tokens_rejected(self):
        asset = service.upload_asset(self.foreign, "signature", self.image())
        draft = service.default_draft()
        draft["signature_id"] = asset.pk
        with self.assertRaises(Exception):
            service.validate_draft(self.program, draft)
        draft["signature_id"] = None
        draft["subject"] = "{password}"
        self.assertEqual(
            self.client.put(
                self.root, {"revision": 1, "draft": draft}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(self.root + f"assets/{asset.pk}/").status_code, 404
        )

    def test_images_validate_real_content_and_preserve_alpha(self):
        response = self.client.post(
            self.root + "assets/", {"kind": "signature", "file": self.image()}
        )
        self.assertEqual(response.status_code, 201, response.data)
        content = self.client.get(self.root + f"assets/{response.data['id']}/").content
        self.assertEqual(Image.open(io.BytesIO(content)).mode, "RGBA")
        for upload in (
            SimpleUploadedFile("bad.png", b"<svg/>", content_type="image/png"),
            self.image("JPEG"),
        ):
            self.assertEqual(
                self.client.post(
                    self.root + "assets/", {"kind": "signature", "file": upload}
                ).status_code,
                400,
            )

    def test_schedule_cannot_precede_finish_and_manual_needs_recipients(self):
        self.config.draft["timing"] = "scheduled"
        self.config.draft["scheduled_at"] = (
            timezone.now() + timedelta(hours=1)
        ).isoformat()
        self.config.save()
        self.assertEqual(
            self.client.post(self.root + "activate/", {"revision": 1}).status_code, 400
        )
        self.config.draft["scheduled_at"] = (
            self.program.datetime_finished + timedelta(hours=1)
        ).isoformat()
        self.config.save()
        self.assertEqual(
            self.client.post(self.root + "activate/", {"revision": 1}).status_code, 201
        )
        self.assertEqual(
            self.client.post(self.root + "activate/", {"revision": 1}).status_code, 400
        )

    def test_issuance_is_idempotent_across_runs_and_freezes_template(self):
        batch = self.batch()
        service.initialize_batch(batch.pk)
        service.initialize_batch(batch.pk)
        service.initialize_batch(self.batch().pk)
        self.assertEqual(ProgramCertificate.objects.count(), 2)
        self.config.draft["director"] = "Другой директор"
        self.config.save()
        self.assertEqual(
            ProgramCertificate.objects.first().batch.snapshot["director"], ""
        )

    def test_rescheduled_finish_delays_automatic_initialization(self):
        snapshot = service.default_draft()
        snapshot["timing"] = "scheduled"
        batch = self.batch(snapshot=snapshot)
        service.initialize_batch(batch.pk)
        self.assertFalse(ProgramCertificate.objects.exists())

    @patch("partner_programs.services.certificates.render_pdf", return_value=b"%PDF-test")
    def test_worker_generates_once_and_sends_real_service_mail(self, render):
        row = self.row()
        service.process(str(row.pk))
        service.process(str(row.pk))
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")
        self.assertEqual(render.call_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.leader.email])
        self.assertIn(str(row.download_token), mail.outbox[0].body)

    @patch("partner_programs.services.certificates.render_pdf", return_value=b"%PDF-test")
    def test_failed_send_retry_uses_same_pdf_and_never_resends_sent(self, render):
        row = self.row()
        with patch(
            "partner_programs.services.certificates.send_certificate",
            side_effect=RuntimeError("provider"),
        ):
            service.process(str(row.pk))
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")
        self.assertEqual(bytes(row.pdf), b"%PDF-test")
        response = self.client.post(self.root + "retry/", {})
        self.assertEqual(response.data["count"], 1)
        service.process(str(row.pk))
        self.assertEqual(render.call_count, 1)
        self.assertEqual(self.client.post(self.root + "retry/", {}).data["count"], 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_pause_blocks_initialization_processing_and_retry(self):
        row = self.row(status="failed")
        self.assertEqual(
            self.client.post(self.root + "queue/pause/", {}).status_code, 200
        )
        self.assertEqual(self.client.post(self.root + "retry/", {}).status_code, 400)
        row.status = "pending"
        row.save()
        with patch("partner_programs.services.certificates.render_pdf") as render:
            service.process(str(row.pk))
            render.assert_not_called()
        self.assertEqual(
            self.client.post(self.root + "queue/resume/", {}).status_code, 200
        )

    def test_journal_filters_search_pagination_and_summary(self):
        row = self.row(status="failed", pdf=b"%PDF", error="Временная ошибка")
        self.row(
            user=self.member,
            email=self.member.email,
            name="Илья",
            status="sent",
            pdf=b"%PDF",
            sent_at=timezone.now(),
        )
        response = self.client.get(
            self.root + "deliveries/?status=failed&search=Крылова&limit=1"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(str(response.data["results"][0]["id"]), str(row.pk))
        self.assertTrue(response.data["results"][0]["pdf_ready"])
        self.assertEqual(
            response.data["summary"], {"total": 2, "ready": 2, "sent": 1, "failed": 1}
        )
        self.assertEqual(
            len(self.client.get(self.root + "deliveries/?status=sent").data["results"]), 1
        )
        self.assertEqual(
            self.client.get(self.root + "deliveries/?status=unknown").status_code, 400
        )

    def test_downloads_only_manager_owner_or_secret_link(self):
        row = self.row(status="sent", pdf=b"%PDF-test")
        path = self.root + f"deliveries/{row.pk}/pdf/"
        self.assertEqual(self.client.get(path).status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(
            self.client.get(f"/programs/{self.program.pk}/certificates/me/").data, []
        )
        self.client.force_authenticate(self.leader)
        own = self.client.get(f"/programs/{self.program.pk}/certificates/me/").data
        self.assertEqual(len(own), 1)
        self.client.force_authenticate(None)
        link = f"/programs/{self.program.pk}/certificates/download/{row.download_token}/"
        self.assertEqual(self.client.get(link).status_code, 200)
        self.assertEqual(
            self.client.get(
                link.replace(str(self.program.pk), str(self.foreign.pk), 1)
            ).status_code,
            404,
        )

    @patch("partner_programs.tasks.send_test_program_certificate.delay")
    def test_test_email_is_only_self_and_rate_limited(self, task):
        response = self.client.post(
            self.root + "test/", {"revision": 1, "email": self.other.email}
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(task.call_args.args[1], self.manager.pk)
        self.assertEqual(
            self.client.post(self.root + "test/", {"revision": 1}).status_code, 400
        )

    @tag("native_pdf")
    def test_pdf_renderer_outputs_a4_cyrillic_without_external_fetch(self):
        content = service.render_pdf(
            service.default_draft(),
            {},
            "Александра Константиновна Добровольская",
            "Программа развития",
            "ПРОБНЫЙ",
            timezone.now(),
        )
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertGreater(len(content), 5000)

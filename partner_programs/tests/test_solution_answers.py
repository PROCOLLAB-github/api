import copy
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch, Mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone
from rest_framework.test import APIClient

from files.content import detect_content_type
from files.models import UserFile
from files.typings import FileInfo
from partner_programs import solution_answers, solution_forms
from partner_programs.solution_api import solution_data
from partner_programs.solution_errors import SolutionError
from partner_programs.solution_models import ProgramSolutionAnswer
from partner_programs.solution_schema import form_data
from partner_programs.tests.helpers import create_user
from partner_programs.tests.test_solution_forms import FormFixture, new_field, call


class AnswerFixture(FormFixture):
    def seed_answers(self):
        self.seed()
        rows = [
            *self.payload()["fields"],
            new_field(position=1, required=True, label="Описание"),
            new_field("number", position=2),
            new_field("checkbox", position=3),
            new_field(
                "file",
                "presentation",
                position=4,
                validation=dict(
                    min_length=None,
                    max_length=None,
                    minimum=None,
                    maximum=None,
                    allowed_extensions=["pdf"],
                    max_file_size_bytes=20971520,
                ),
            ),
            new_field("url", "repository", position=5),
        ]
        solution_forms.save_form(
            program_id=self.program.pk, actor=self.manager, **self.payload(fields=rows)
        )
        self.fields = {
            field["type"]: field for field in form_data(self.program)["fields"]
        }
        self.url = f"/programs/{self.program.pk}/solutions/{self.solution.pk}/"

    def command(self, **changes):
        self.solution.refresh_from_db()
        return dict(
            expected_version=self.solution.version,
            expected_form_revision=form_data(self.program)["revision"],
            **changes,
        )

    def save_answers(self, answers=None, actor=None, **changes):
        if answers is not None:
            changes["answers"] = answers
        return call(actor or self.captain, "patch", self.url, self.command(**changes))

    def upload(
        self,
        *,
        user=None,
        mime="application/pdf",
        detected="application/pdf",
        size=100,
        link=None,
        extension="pdf",
    ):
        index = UserFile.objects.count() + 1
        return UserFile.objects.create(
            user=user or self.captain,
            link=link or f"https://cdn.test/uploads/file-{index}.{extension}",
            name=f"file-{index}",
            extension=extension,
            mime_type=mime,
            detected_mime_type=detected,
            size=size,
        )


class SolutionAnswerTests(AnswerFixture, TestCase):
    def setUp(self):
        self.seed_answers()

    def test_partial_save_incomplete_form_keeps_zero_false_and_omitted_values(self):
        result = self.save_answers(
            [
                {"field_id": self.fields["number"]["id"], "value": 0},
                {"field_id": self.fields["checkbox"]["id"], "value": False},
            ],
            name="Моя заявка",
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["version"], 2)
        self.assertEqual(result.data["name"], "Моя заявка")
        self.assertTrue(result.data["permissions"]["can_edit"])
        self.assertFalse(result.data["readiness"]["is_ready"])
        self.assertEqual(self.solution.answers.count(), 2)
        saved = self.save_answers(
            [{"field_id": self.fields["textarea"]["id"], "value": "Описание"}]
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(self.solution.answers.count(), 3)
        values = {answer.field_id: answer.value for answer in self.solution.answers.all()}
        self.assertIs(values[self.fields["checkbox"]["id"]], False)
        self.assertEqual(values[self.fields["number"]["id"]], 0)

    def test_response_matches_frozen_solution_schema(self):
        response = self.save_answers(
            [{"field_id": self.fields["textarea"]["id"], "value": "Текст"}]
        )
        self.assertEqual(response.status_code, 200, response.data)
        spec = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/contracts/program-solutions-v1/openapi.json"
            ).read_text(encoding="utf-8")
        )
        from jsonschema import Draft202012Validator, FormatChecker

        Draft202012Validator(
            {"components": spec["components"], "$ref": "#/components/schemas/Solution"},
            format_checker=FormatChecker(),
        ).validate(response.data)

    def test_explicit_clear_deletes_only_requested_answers_and_not_file_binary(self):
        upload = self.upload()
        saved = self.save_answers(
            [
                {"field_id": self.fields["textarea"]["id"], "value": "Текст"},
                {"field_id": self.fields["number"]["id"], "value": 0},
                {"field_id": self.fields["file"]["id"], "value": {"url": upload.link}},
            ]
        )
        self.assertEqual(saved.status_code, 200, saved.data)
        cleared = self.save_answers(
            [
                {"field_id": self.fields["textarea"]["id"], "value": "   "},
                {"field_id": self.fields["file"]["id"], "value": None},
            ]
        )
        self.assertEqual(cleared.status_code, 200, cleared.data)
        self.assertEqual(self.solution.answers.count(), 1)
        self.assertTrue(UserFile.objects.filter(pk=upload.pk).exists())

    def test_types_foreign_fields_duplicates_and_constraints_fail_atomically(self):
        foreign = self.program.__class__.objects.create(
            name="Другая",
            tag="other",
            description="",
            city="",
            data_schema={},
            draft=False,
            datetime_registration_ends=timezone.now(),
            datetime_started=timezone.now(),
            datetime_finished=timezone.now(),
        )
        from partner_programs.models import PartnerProgramField

        other = PartnerProgramField.objects.create(
            partner_program=foreign, name="other", label="Other", field_type="text"
        )
        bad = [
            [{"field_id": self.fields["number"]["id"], "value": True}],
            [{"field_id": self.fields["number"]["id"], "value": ""}],
            [{"field_id": self.fields["checkbox"]["id"], "value": "false"}],
            [
                {
                    "field_id": self.fields["file"]["id"],
                    "value": "https://external.test/a.pdf",
                }
            ],
            [{"field_id": self.fields["select"]["id"], "value": "Другой кейс"}],
            [{"field_id": self.fields["url"]["id"], "value": "javascript:alert(1)"}],
            [{"field_id": other.pk, "value": "Чужое"}],
            [
                {"field_id": self.fields["textarea"]["id"], "value": "A"},
                {"field_id": self.fields["textarea"]["id"], "value": "B"},
            ],
        ]
        for changes in bad:
            with self.subTest(changes=changes):
                result = self.save_answers(changes, name="Не сохранять")
                self.assert_error(result, "invalid_answers", 400)
                self.solution.refresh_from_db()
                self.assertEqual(self.solution.version, 1)
                self.assertEqual(self.solution.name, "Новое решение")
                self.assertEqual(self.solution.answers.count(), 0)

    def test_syntax_requires_both_versions_one_change_and_strict_answer_shape(self):
        for body in (
            {"name": "X"},
            self.command(),
            self.command(name=3),
            self.command(name=""),
            self.command(answers=[{"field_id": True, "value": 0}]),
            self.command(answers=[{"field_id": 1, "value": [1, 2]}]),
            self.command(
                answers=[
                    {"field_id": 1, "value": {"url": "x", "user_id": self.captain.pk}}
                ]
            ),
            {**self.command(name="X"), "captain_id": self.captain.pk},
        ):
            result = call(self.captain, "patch", self.url, body)
            self.assert_error(result, "validation_error", 400)
        self.assertEqual(self.solution.answers.count(), 0)

    def test_stale_versions_and_form_revision_never_overwrite(self):
        body = self.command(name="Первое")
        first = call(self.captain, "patch", self.url, body)
        self.assertEqual(first.status_code, 200)
        self.assert_error(call(self.captain, "patch", self.url, body), "version_conflict")
        body = self.command(name="Второе")
        body["expected_form_revision"] = "b" * 64
        self.assert_error(
            call(self.captain, "patch", self.url, body), "form_revision_conflict"
        )
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.name, "Первое")

    def test_only_captain_edits_and_foreign_solution_is_hidden(self):
        from partner_programs.solution_models import ProgramSolutionMember

        member = create_user()
        ProgramSolutionMember.objects.create(solution=self.solution, user=member)
        for actor in (member, self.manager):
            self.assert_error(
                self.save_answers([], actor=actor), "not_solution_captain", 403
            )
        self.assert_error(self.save_answers([], actor=create_user()), "not_found", 404)

    def test_deadline_does_not_block_draft_save_but_mode_rollback_does(self):
        self.program.datetime_project_submission_ends = (
            timezone.now() - timezone.timedelta(days=1)
        )
        self.program.save()
        result = self.save_answers([], name="После срока")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(result.data["submission"]["submission_open"])
        self.program.solution_storage_mode = "legacy_project"
        self.program.save()
        self.assert_error(
            self.save_answers([], name="Не сохранять"), "solution_mode_unavailable"
        )
        self.assertFalse(
            call(self.captain, "get", self.url).data["permissions"]["can_edit"]
        )

    def freeze(self):
        self.solution.refresh_from_db()
        data = solution_data(self.solution, self.captain)
        stamp = timezone.now()
        self.solution.status = "submitted"
        self.solution.submitted_at = stamp
        self.solution.submission_snapshot = {
            "name": data["name"],
            "captain_id": data["captain_id"],
            "members": data["team"]["members"],
            "form": {**data["form"], "is_snapshot": True},
            "answers": data["answers"],
            "submitted_at": stamp.isoformat(),
        }
        self.solution.save()

    def test_frozen_solution_rejects_edit_before_stale_version_and_keeps_snapshot(self):
        self.freeze()
        snapshot = copy.deepcopy(self.solution.submission_snapshot)
        command = self.command(name="Не сохранять")
        command["expected_version"] = 999
        self.assert_error(call(self.captain, "patch", self.url, command), "team_frozen")
        self.solution.refresh_from_db()
        self.assertEqual(self.solution.submission_snapshot, snapshot)
        self.assertFalse(
            call(self.captain, "get", self.url).data["permissions"]["can_edit"]
        )

    def test_file_registration_owner_type_and_size_are_rechecked(self):
        valid = self.upload()
        accepted = self.save_answers(
            [{"field_id": self.fields["file"]["id"], "value": {"url": valid.link}}]
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)
        for upload, code in (
            (self.upload(user=create_user()), "file_forbidden"),
            (self.upload(detected="application/zip"), "file_type_mismatch"),
            (self.upload(size=20971521), "file_too_large"),
            (
                self.upload(extension="zip", detected="application/zip"),
                "file_type_not_allowed",
            ),
        ):
            result = self.save_answers(
                [{"field_id": self.fields["file"]["id"], "value": {"url": upload.link}}]
            )
            self.assert_error(result, "invalid_answers", 400)
            self.assertEqual(result.data["errors"][0]["code"], code)
        result = self.save_answers(
            [
                {
                    "field_id": self.fields["file"]["id"],
                    "value": {"url": "https://external.test/no.pdf"},
                }
            ]
        )
        self.assert_error(result, "invalid_answers", 400)

    def test_already_owned_imported_file_can_move_between_fields_without_new_project(
        self,
    ):
        source = self.upload(user=create_user())
        ProgramSolutionAnswer.objects.create(
            solution=self.solution,
            field_id=self.fields["file"]["id"],
            value={"url": source.link},
        )
        result = solution_forms.save_form(
            program_id=self.program.pk,
            actor=self.manager,
            **self.payload(
                fields=[*self.payload()["fields"], new_field("file", position=10)]
            ),
        )
        target = result["form"]["fields"][-1]
        response = self.save_answers(
            [
                {"field_id": self.fields["file"]["id"], "value": None},
                {"field_id": target["id"], "value": {"url": source.link}},
            ]
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.solution.answers.count(), 1)
        self.assertEqual(self.solution.answers.get().field_id, target["id"])

    def test_upload_returns_old_url_shape_and_stores_content_type_from_actual_bytes(self):
        from files.views import FileView

        def stored(file, user):
            return FileInfo(
                url="https://cdn.test/upload.pdf",
                size=file.size,
                name=file.name,
                extension=file.extension,
                mime_type=file.content_type,
                detected_mime_type=file.detected_mime_type,
            )

        with patch.object(FileView.cdn.storage, "upload", side_effect=stored):
            client = APIClient()
            client.force_authenticate(self.captain)
            response = client.post(
                "/files/",
                {
                    "file": SimpleUploadedFile(
                        "file.pdf", b"not a pdf", content_type="application/pdf"
                    )
                },
                format="multipart",
            )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data, {"url": "https://cdn.test/upload.pdf"})
        upload = UserFile.objects.get(pk=response.data["url"])
        self.assertEqual(upload.detected_mime_type, "text/plain")
        result = self.save_answers(
            [{"field_id": self.fields["file"]["id"], "value": response.data}]
        )
        self.assert_error(result, "invalid_answers", 400)

    def test_original_image_preserves_bytes_and_default_upload_still_converts(self):
        from PIL import Image
        from files.views import FileView

        image = BytesIO()
        Image.new("RGB", (4, 4), "purple").save(image, format="PNG")
        original = image.getvalue()
        stored_bytes = []

        def stored(file, user):
            stored_bytes.append(
                file.buffer.read() if hasattr(file.buffer, "read") else bytes(file.buffer)
            )
            return FileInfo(
                url=f"https://cdn.test/image-{len(stored_bytes)}.{file.extension}",
                size=file.size,
                name=file.name,
                extension=file.extension,
                mime_type=file.content_type,
                detected_mime_type=file.detected_mime_type,
            )

        client = APIClient()
        client.force_authenticate(self.captain)
        with patch.object(FileView.cdn.storage, "upload", side_effect=stored):
            kept = client.post(
                "/files/?preserve_original=true",
                {
                    "file": SimpleUploadedFile(
                        "photo.png", original, content_type="image/png"
                    )
                },
                format="multipart",
            )
            converted = client.post(
                "/files/",
                {
                    "file": SimpleUploadedFile(
                        "photo.png", original, content_type="image/png"
                    )
                },
                format="multipart",
            )
        self.assertEqual(kept.status_code, 201, kept.data)
        self.assertEqual(kept.data, {"url": "https://cdn.test/image-1.png"})
        self.assertEqual(converted.data, {"url": "https://cdn.test/image-2.webp"})
        self.assertEqual(stored_bytes[0], original)
        self.assertNotEqual(stored_bytes[1], original)
        self.assertEqual(
            UserFile.objects.get(pk=kept.data["url"]).detected_mime_type, "image/png"
        )
        self.assertEqual(
            UserFile.objects.get(pk=converted.data["url"]).detected_mime_type,
            "image/webp",
        )

    @override_settings(SELECTEL_SWIFT_URL="https://cdn.test/uploads/")
    def test_old_upload_is_verified_only_inside_owned_cdn_without_redirects(self):
        old = self.upload(detected="")
        response = Mock(status_code=200)
        response.iter_content.return_value = [b"%PDF-1.7\nfile\n%%EOF"]
        with patch(
            "partner_programs.solution_files.requests.get", return_value=response
        ) as get:
            result = self.save_answers(
                [{"field_id": self.fields["file"]["id"], "value": {"url": old.link}}]
            )
        self.assertEqual(result.status_code, 200, result.data)
        get.assert_called_once_with(
            old.link, stream=True, timeout=(5, 10), allow_redirects=False
        )
        old.refresh_from_db()
        self.assertEqual(old.detected_mime_type, "application/pdf")
        external = self.upload(detected="", link="http://127.0.0.1/private.pdf")
        with patch("partner_programs.solution_files.requests.get") as get:
            result = self.save_answers(
                [{"field_id": self.fields["file"]["id"], "value": {"url": external.link}}]
            )
        self.assert_error(result, "invalid_answers", 400)
        get.assert_not_called()

    def test_submitted_file_deletion_is_blocked_before_cdn_and_through_orm(self):
        from files.views import FileView

        upload = self.upload()
        self.save_answers(
            [{"field_id": self.fields["file"]["id"], "value": {"url": upload.link}}]
        )
        self.freeze()
        client = APIClient()
        client.force_authenticate(self.captain)
        with patch.object(FileView.cdn, "delete") as cdn:
            response = client.delete("/files/", QUERY_STRING="link=" + upload.link)
        self.assert_error(response, "file_in_use")
        cdn.assert_not_called()
        with self.assertRaises(ProtectedError), transaction.atomic():
            UserFile.objects.filter(pk=upload.pk).delete()
        self.assertTrue(UserFile.objects.filter(pk=upload.pk).exists())

    def test_draft_file_deletion_keeps_existing_semantics(self):
        from files.views import FileView

        upload = self.upload()
        client = APIClient()
        client.force_authenticate(self.captain)
        with patch.object(FileView.cdn, "delete") as cdn:
            response = client.delete("/files/", QUERY_STRING="link=" + upload.link)
        self.assertEqual(response.status_code, 204)
        cdn.assert_called_once_with(upload.link)

    def test_snapshot_reference_alone_protects_admin_bulk_delete_before_any_cdn_call(
        self,
    ):
        from django.contrib.admin.sites import AdminSite
        from django.core.exceptions import PermissionDenied
        from files.admin import UserFileAdmin

        protected = self.upload()
        unused = self.upload()
        self.freeze()
        self.solution.submission_snapshot["answers"] = [
            {"field_id": self.fields["file"]["id"], "value": {"url": protected.link}}
        ]
        self.solution.save()
        self.assertFalse(self.solution.answers.exists())
        admin = UserFileAdmin(UserFile, AdminSite())
        with patch.object(admin.cdn, "delete") as cdn:
            with self.assertRaises(PermissionDenied), transaction.atomic():
                admin.delete_queryset(
                    Mock(), UserFile.objects.filter(pk__in=[protected.pk, unused.pk])
                )
        cdn.assert_not_called()
        self.assertTrue(UserFile.objects.filter(pk=protected.pk).exists())
        self.assertTrue(UserFile.objects.filter(pk=unused.pk).exists())

    @override_settings(SELECTEL_SWIFT_URL="https://cdn.test/uploads/")
    def test_legacy_redirect_is_rejected_without_binding_or_following(self):
        old = self.upload(detected="")
        response = Mock(status_code=302)
        with patch(
            "partner_programs.solution_files.requests.get", return_value=response
        ) as get:
            result = self.save_answers(
                [{"field_id": self.fields["file"]["id"], "value": {"url": old.link}}]
            )
        self.assert_error(result, "invalid_answers", 400)
        self.assertEqual(result.data["errors"][0]["code"], "file_unavailable")
        self.assertFalse(self.solution.answers.exists())
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        response.close.assert_called_once()

    def test_byte_inspection_does_not_consume_stream_or_trust_filename(self):
        stream = BytesIO(b"%PDF-1.7\n")
        self.assertEqual(detect_content_type(stream), "application/pdf")
        self.assertEqual(stream.tell(), 0)
        import zipfile

        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("readme.txt", "test")
        archive.seek(0)
        self.assertEqual(detect_content_type(archive), "application/zip")
        self.assertFalse(archive.closed)
        self.assertEqual(archive.tell(), 0)


class SolutionAnswerConcurrencyTests(AnswerFixture, TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_patches_with_same_version_serialize(self):
        self.seed_answers()
        command = self.command(name="Название")
        barrier = Barrier(2)

        def write(label):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                solution_answers.update_solution(
                    program_id=self.program.pk,
                    solution_id=self.solution.pk,
                    actor=self.captain,
                    **{**command, "name": label},
                )
                return "saved"
            except SolutionError as error:
                return error.payload["code"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["Первое", "Второе"]))
        self.assertCountEqual(results, ["saved", "version_conflict"])

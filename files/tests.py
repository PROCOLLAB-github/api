from io import BytesIO
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import requests
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.admin.utils import quote
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from PIL import Image

from chats.exceptions import MessageValidationException
from chats.services.messages import create_direct_message
from files.content import detect_content_type
from files.models import UserFile
from projects.tests.helpers import create_staff_user

STORAGE = "https://storage.example.test/v1/account/media/"
DIRECT_STORAGE = "https://storage.example.test/v1/account/private-direct/"


class FileContentTypeTests(SimpleTestCase):
    def test_wrong_png_checksum_has_no_image_preview(self):
        original = BytesIO()
        Image.new("RGB", (2, 2)).save(original, format="PNG")
        damaged = bytearray(original.getvalue())
        image_data = damaged.index(b"IDAT") + 4
        damaged[image_data] ^= 1
        stream = BytesIO(damaged)

        self.assertEqual(detect_content_type(original), "image/png")
        self.assertEqual(detect_content_type(stream), "application/octet-stream")
        self.assertEqual(stream.tell(), 0)


@override_settings(ALLOWED_HOSTS=["testserver"], SELECTEL_SWIFT_URL=STORAGE)
class DirectAttachmentUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_staff_user(prefix="direct-upload")

    def upload(self, suffix):
        api = APIClient()
        api.force_authenticate(self.user)
        return api.post(
            "/files/" + suffix, {"file": SimpleUploadedFile("notes.txt", b"contents")}, secure=True
        )

    @override_settings(SELECTEL_DIRECT_CHAT_SWIFT_URL=DIRECT_STORAGE)
    @patch("files.service.SelectelSwiftStorage._get_auth_token", return_value="test")
    @patch("files.service.requests.put", return_value=Mock(status_code=201))
    def test_scope_routes_only_direct_attachments_to_the_private_container(self, put, _token):
        direct = self.upload("?scope=direct_chat")
        other = self.upload("?preserve_original=true")
        self.assertEqual((direct.status_code, other.status_code), (201, 201))
        self.assertTrue(direct.json()["url"].startswith(DIRECT_STORAGE))
        self.assertTrue(other.json()["url"].startswith(STORAGE))
        self.assertEqual([call.args[0] for call in put.call_args_list], [direct.json()["url"], other.json()["url"]])

    @override_settings(SELECTEL_DIRECT_CHAT_SWIFT_URL="")
    @patch("files.service.requests.put")
    def test_private_upload_does_not_fall_back_to_public_storage(self, put):
        self.assertEqual(self.upload("?scope=direct_chat").status_code, 503)
        put.assert_not_called()

    @override_settings(SELECTEL_DIRECT_CHAT_SWIFT_URL=DIRECT_STORAGE)
    def test_direct_message_requires_private_storage_for_new_files(self):
        recipient = create_staff_user(prefix="direct-recipient")
        public = UserFile.objects.create(user=self.user, link=STORAGE + "notes.txt")
        private = UserFile.objects.create(user=self.user, link=DIRECT_STORAGE + "notes.txt")
        with self.assertRaisesMessage(MessageValidationException, "Загрузите вложения личного чата заново."):
            create_direct_message(author=self.user, other_user=recipient, text="", file_urls=[public.pk])
        message, created = create_direct_message(
            author=self.user, other_user=recipient, text="", file_urls=[private.pk]
        )
        self.assertTrue(created)
        self.assertRegex(message["files"][0]["link"], r"^/chats/directs/.+/download/$")


@override_settings(ALLOWED_HOSTS=["testserver"], SELECTEL_SWIFT_URL=STORAGE)
class FileDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = create_staff_user(prefix="file-deletion")
        cls.file = UserFile.objects.create(link=STORAGE + "a.pdf", user=cls.user)

    @patch("files.service.SelectelSwiftStorage._get_auth_token", return_value="test")
    @patch("files.service.requests.delete")
    def test_api_keeps_upload_until_storage_confirms_delete(self, delete, _token):
        api = APIClient()
        api.force_authenticate(self.user)
        url = "/files/?" + urlencode({"link": self.file.pk})
        delete.side_effect = [
            requests.Timeout(),
            Mock(status_code=302),
            Mock(status_code=503),
            Mock(status_code=404),
        ]

        for _ in range(3):
            response = api.delete(url, secure=True)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["code"], "file_delete_failed")
            self.assertTrue(UserFile.objects.filter(pk=self.file.pk).exists())
        self.assertEqual(api.delete(url, secure=True).status_code, 204)
        self.assertFalse(UserFile.objects.filter(pk=self.file.pk).exists())
        delete.assert_called_with(
            self.file.pk,
            headers={"X-Auth-Token": "test"},
            timeout=(5, 15),
            allow_redirects=False,
        )

    @patch("files.service.SelectelSwiftStorage._get_auth_token")
    @patch("files.service.requests.delete")
    def test_api_does_not_send_credentials_for_unmanaged_upload(self, delete, token):
        file = UserFile.objects.create(
            link="https://external.example.test/a.pdf", user=self.user
        )
        api = APIClient()
        api.force_authenticate(self.user)
        response = api.delete("/files/?" + urlencode({"link": file.pk}), secure=True)
        self.assertEqual(response.status_code, 502)
        self.assertTrue(UserFile.objects.filter(pk=file.pk).exists())
        token.assert_not_called()
        delete.assert_not_called()

    @patch("files.service.SelectelSwiftStorage._get_auth_token", return_value="test")
    @patch("files.service.requests.delete", return_value=Mock(status_code=503))
    def test_admin_reports_failure_and_preserves_file(self, delete, _token):
        self.client.force_login(self.user)
        url = reverse("admin:files_userfile_delete", args=[quote(self.file.pk)])
        response = self.client.post(url, {"post": "yes"}, secure=True, follow=True)
        self.assertContains(response, "Не удалось удалить файл из хранилища.")
        self.assertTrue(UserFile.objects.filter(pk=self.file.pk).exists())
        self.assertFalse(LogEntry.objects.filter(action_flag=DELETION).exists())
        delete.assert_called_once()

    @patch("files.service.SelectelSwiftStorage._get_auth_token", return_value="test")
    @patch("files.service.requests.delete")
    def test_admin_bulk_records_only_confirmed_deletions(self, delete, _token):
        second = UserFile.objects.create(link=STORAGE + "b.pdf", user=self.user)
        delete.side_effect = [Mock(status_code=204), Mock(status_code=503)]
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("admin:files_userfile_changelist"),
            {
                "action": "delete_selected",
                "post": "yes",
                ACTION_CHECKBOX_NAME: [self.file.pk, second.pk],
            },
            secure=True,
            follow=True,
        )
        self.assertContains(response, "Удалено файлов: 1.")
        self.assertContains(response, "Не удалось удалить файлов: 1.")
        self.assertFalse(UserFile.objects.filter(pk=self.file.pk).exists())
        self.assertTrue(UserFile.objects.filter(pk=second.pk).exists())
        self.assertEqual(
            list(
                LogEntry.objects.filter(action_flag=DELETION).values_list(
                    "object_id", flat=True
                )
            ),
            [self.file.pk],
        )

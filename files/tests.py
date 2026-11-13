from unittest.mock import Mock, patch
from urllib.parse import urlencode

import requests
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.admin.utils import quote
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from files.models import UserFile
from projects.tests.helpers import create_staff_user

STORAGE = "https://storage.example.test/v1/account/media/"


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

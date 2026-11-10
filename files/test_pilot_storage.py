"""Пилот пишет и удаляет только собственные файлы без вызовов Selectel."""

from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlencode

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from files.models import UserFile
from files.service import CDN, configured_storage
from partner_programs.tests.helpers import create_user


@override_settings(
    PILOT_LOCAL_FILES=True,
    WHITE_LABEL_FRONTEND_URL="https://pilot.example.test",
    MEDIA_URL="/backend/media/",
)
class PilotStorageTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.media = override_settings(MEDIA_ROOT=self.directory.name)
        self.media.enable()
        self.addCleanup(self.media.disable)
        # В приложении адаптер выбирается при запуске. В тестовом процессе
        # URLconf уже загружен до override_settings, поэтому повторяем этот выбор.
        storage = patch("files.views.FileView.cdn", CDN(storage=configured_storage()))
        storage.start()
        self.addCleanup(storage.stop)
        self.user = create_user(is_active=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("files.service.requests.put")
    @patch("files.service.requests.post")
    def test_upload_and_delete_use_local_instance_storage(self, post, put):
        upload = SimpleUploadedFile(
            "case.txt", b"synthetic case document", content_type="text/plain"
        )
        response = self.client.post(
            "/files/?preserve_original=true", {"file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, 201, response.data)
        url = response.data["url"]
        self.assertTrue(
            url.startswith("https://pilot.example.test/backend/media/uploads/")
        )
        self.assertTrue(UserFile.objects.filter(link=url, user=self.user).exists())
        from pathlib import Path

        files = [p for p in Path(self.directory.name).rglob("*") if p.is_file()]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b"synthetic case document")
        deleted = self.client.delete("/files/?" + urlencode({"link": url}))
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(files[0].exists())
        self.assertFalse(UserFile.objects.filter(link=url).exists())
        post.assert_not_called()
        put.assert_not_called()

    def test_other_owner_cannot_delete_file(self):
        other = create_user(is_active=True)
        row = UserFile.objects.create(
            user=other,
            link="https://pilot.example.test/backend/media/uploads/other.txt",
            name="case",
            extension="txt",
            size=10,
        )
        response = self.client.delete("/files/?" + urlencode({"link": row.link}))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserFile.objects.filter(pk=row.pk).exists())

    def test_delete_rejects_external_urls_and_traversal(self):
        from files.service import PilotFileStorage

        storage = PilotFileStorage()
        for url in (
            "https://outside.example.test/file",
            "https://pilot.example.test/backend/media/%2e%2e/secret",
            "https://pilot.example.test/backend/media/%2fetc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                storage.delete(url)

from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image

from files.service import LocalFileSystemStorage, File


class LocalFileSystemStorageTests(SimpleTestCase):
    def test_upload_converted_image_as_readable_webp(self):
        with TemporaryDirectory() as media_root:
            upload = BytesIO()
            Image.new("RGB", (8, 8), color="red").save(upload, format="JPEG")
            upload.seek(0)

            django_file = SimpleUploadedFile(
                "avatar.jpg",
                upload.read(),
                content_type="image/jpeg",
            )
            user = SimpleNamespace(email="user@example.com")

            with override_settings(
                MEDIA_ROOT=media_root,
                MEDIA_URL="/media/",
                LOCAL_MEDIA_BASE_URL="http://127.0.0.1:8000",
            ):
                info = LocalFileSystemStorage().upload(File(django_file), user)

            self.assertEqual(info.extension, "webp")
            self.assertEqual(info.mime_type, "image/webp")
            self.assertGreater(info.size, 0)

    def test_upload_can_preserve_original_image_format(self):
        with TemporaryDirectory() as media_root:
            upload = BytesIO()
            Image.new("RGB", (8, 8), color="blue").save(upload, format="PNG")
            upload.seek(0)

            django_file = SimpleUploadedFile(
                "document.png",
                upload.read(),
                content_type="image/png",
            )
            user = SimpleNamespace(email="user@example.com")

            with override_settings(
                MEDIA_ROOT=media_root,
                MEDIA_URL="/media/",
                LOCAL_MEDIA_BASE_URL="http://127.0.0.1:8000",
            ):
                info = LocalFileSystemStorage().upload(
                    File(django_file, convert_images=False),
                    user,
                )

            self.assertEqual(info.extension, "png")
            self.assertEqual(info.mime_type, "image/png")
            self.assertGreater(info.size, 0)

    def test_upload_accepts_buffer_without_read_method(self):
        with TemporaryDirectory() as media_root:
            file = SimpleNamespace(
                name="avatar",
                extension="webp",
                content_type="image/webp",
                size=3,
                buffer=memoryview(b"abc"),
            )
            user = SimpleNamespace(email="user@example.com")

            with override_settings(
                MEDIA_ROOT=media_root,
                MEDIA_URL="/media/",
                LOCAL_MEDIA_BASE_URL="http://127.0.0.1:8000",
            ):
                info = LocalFileSystemStorage().upload(file, user)

            self.assertEqual(info.extension, "webp")
            self.assertEqual(info.mime_type, "image/webp")
            self.assertEqual(info.size, 3)

    def test_upload_does_not_duplicate_media_prefix_when_base_url_includes_media(self):
        with TemporaryDirectory() as media_root:
            file = SimpleNamespace(
                name="avatar",
                extension="webp",
                content_type="image/webp",
                size=3,
                buffer=memoryview(b"abc"),
            )
            user = SimpleNamespace(email="user@example.com")

            with override_settings(
                MEDIA_ROOT=media_root,
                MEDIA_URL="/media/",
                LOCAL_MEDIA_BASE_URL="https://procollab.pro/media",
            ):
                info = LocalFileSystemStorage().upload(file, user)

            self.assertTrue(info.url.startswith("https://procollab.pro/media/uploads/"))
            self.assertNotIn("/media/media/", info.url)

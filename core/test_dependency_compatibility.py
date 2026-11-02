"""Compatibility of persisted credentials, static assets and image uploads."""

from io import BytesIO
from types import SimpleNamespace

from django.contrib.auth.hashers import check_password
from django.core.files.storage import storages
from django.test import SimpleTestCase, override_settings
from PIL import Image
from whitenoise.storage import CompressedStaticFilesStorage

from files.helpers import convert_image_to_webp


@override_settings(
    PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.BCryptPasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    ]
)
class PersistedPasswordCompatibilityTests(SimpleTestCase):
    # Synthetic fixtures produced by the previous Django 4.2.11 / bcrypt 4.1.2.
    def test_existing_long_bcrypt_password_still_authenticates(self):
        encoded = "bcrypt$$2b$04$qs8/QCj6RsBopogj..srsuvHeg/qOtoW44PjQvsji2su7J6I9z7TK"
        self.assertTrue(check_password("legacy-password-" + "x" * 100, encoded))
        self.assertFalse(check_password("different-password-" + "x" * 100, encoded))

    def test_existing_pbkdf2_password_still_authenticates(self):
        encoded = (
            "pbkdf2_sha256$390000$migration-test-salt$"
            "cGWmSyv+hMl8eGjeBZL5rFJkIvidubO6dg6yOT99zIM="
        )
        self.assertTrue(check_password("legacy-secret-2026", encoded))
        self.assertFalse(check_password("different-secret", encoded))


class DependencyIntegrationTests(SimpleTestCase):
    def test_static_assets_keep_whitenoise_compression(self):
        self.assertIsInstance(storages["staticfiles"], CompressedStaticFilesStorage)

    def test_uploaded_rgba_image_can_be_converted_to_webp(self):
        upload = BytesIO()
        Image.new("RGBA", (8, 6), (40, 80, 120, 51)).save(upload, format="PNG")
        upload.seek(0)
        encoded = convert_image_to_webp(SimpleNamespace(file=upload))
        with Image.open(BytesIO(encoded.buffer())) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (8, 6))
            self.assertEqual(image.getchannel("A").getextrema(), (51, 51))

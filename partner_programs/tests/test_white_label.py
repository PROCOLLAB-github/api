"""Проверки изолированного режима и сохранения обычной регистрации."""

import io
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from partner_programs.models import (
    PartnerProgram,
    PartnerProgramUserProfile,
    PendingProgramRegistration,
    ProgramRegistration,
)
from partner_programs.services.native_registration import confirmation_token
from partner_programs.tests.helpers import create_partner_program, create_user
from partner_programs.tests.test_native_registration import TEST_REGISTRATION_SETTINGS
from procollab.white_label import check_white_label
from users.models import CustomUser


WHITE_LABEL_SETTINGS = {
    "WHITE_LABEL_ENABLED": True,
    "WHITE_LABEL_PROGRAM_ID": 1,
    "WHITE_LABEL_BRAND_NAME": "Кейс-чемпионат клиента",
    "WHITE_LABEL_FRONTEND_URL": "https://championship.example.test",
    "WHITE_LABEL_LOGO_URL": "https://championship.example.test/logo.svg",
}


@override_settings(**WHITE_LABEL_SETTINGS)
class WhiteLabelConfigurationTests(SimpleTestCase):
    def test_valid_configuration(self):
        self.assertEqual(check_white_label(None), [])

    def test_invalid_program_and_brand(self):
        for key, value in (
            ("WHITE_LABEL_PROGRAM_ID", 0),
            ("WHITE_LABEL_PROGRAM_ID", True),
            ("WHITE_LABEL_BRAND_NAME", ""),
            ("WHITE_LABEL_BRAND_NAME", "Имя\nПодмена"),
        ):
            with self.subTest(key=key, value=value), override_settings(**{key: value}):
                self.assertEqual(check_white_label(None)[0].id, "white_label.E001")

    def test_untrusted_url_components_are_rejected(self):
        for url in (
            "http://championship.example.test",
            "https://user:pass@championship.example.test",
            "https://championship.example.test/path",
            "https://championship.example.test?next=https://other.example.test",
            "https://championship.example.test#fragment",
            "javascript:alert(1)",
        ):
            with self.subTest(url=url), override_settings(WHITE_LABEL_FRONTEND_URL=url):
                self.assertTrue(check_white_label(None))

    def test_local_development_origin(self):
        with override_settings(WHITE_LABEL_FRONTEND_URL="http://localhost:8317"):
            self.assertEqual(check_white_label(None), [])

    def test_disabled_mode_ignores_unused_configuration(self):
        with override_settings(WHITE_LABEL_ENABLED=False, WHITE_LABEL_PROGRAM_ID=0):
            self.assertEqual(check_white_label(None), [])

    def test_logo_credentials_are_not_exposed_as_public_configuration(self):
        with override_settings(
            WHITE_LABEL_LOGO_URL="https://user:password@championship.example.test/logo.svg"
        ):
            self.assertTrue(check_white_label(None))


@override_settings(**TEST_REGISTRATION_SETTINGS)
class WhiteLabelRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.program = create_partner_program()
        self.other_program = create_partner_program()
        for program in (self.program, self.other_program):
            ProgramRegistration.objects.create(
                program=program,
                draft={"mode": "native", "fields": []},
                published={"mode": "native", "fields": []},
                published_version=1,
            )
        self.mode = override_settings(
            **{**WHITE_LABEL_SETTINGS, "WHITE_LABEL_PROGRAM_ID": self.program.pk}
        )
        self.mode.enable()
        self.addCleanup(self.mode.disable)
        self.root = f"/programs/{self.program.pk}/registration/"

    def payload(self, **overrides):
        data = {
            "version": 1,
            "answers": {},
            "email": "new-participant@example.test",
            "password": "Secure-demo-password-2030",
            "repeat_password": "Secure-demo-password-2030",
            "accept_policy": True,
            "accept_age": True,
        }
        return {**data, **overrides}

    def signup(self, **overrides):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                self.root + "signup/", self.payload(**overrides), format="json"
            )

    def test_public_configuration_has_only_safe_fields(self):
        response = self.client.get("/instance/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {
                "enabled",
                "program_id",
                "brand_name",
                "logo_url",
                "frontend_url",
                "registration_url",
                "program_url",
            },
        )
        self.assertEqual(response.data["program_id"], self.program.pk)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertTrue(
            response.data["registration_url"].startswith(
                "https://championship.example.test/"
            )
        )

    def test_short_mode_is_limited_to_the_configured_program(self):
        data = self.client.get(self.root).data
        self.assertEqual(data["account_mode"], "email_password")
        self.assertEqual(
            data["branding"],
            {
                "name": WHITE_LABEL_SETTINGS["WHITE_LABEL_BRAND_NAME"],
                "logo_url": WHITE_LABEL_SETTINGS["WHITE_LABEL_LOGO_URL"],
            },
        )
        other = f"/programs/{self.other_program.pk}/registration/"
        self.assertNotIn("account_mode", self.client.get(other).data)
        self.assertNotIn("branding", self.client.get(other).data)
        response = self.client.post(other + "signup/", self.payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("first_name", response.data)
        self.assertIn("last_name", response.data)
        self.assertIn("birthday", response.data)

    def test_disabled_mode_keeps_the_original_form(self):
        with override_settings(WHITE_LABEL_ENABLED=False):
            self.assertEqual(self.client.get("/instance/").data, {"enabled": False})
            self.assertNotIn("account_mode", self.client.get(self.root).data)
            self.assertNotIn("branding", self.client.get(self.root).data)
            response = self.signup()
        self.assertEqual(response.status_code, 400)
        self.assertIn("birthday", response.data)

    def test_signup_confirm_and_login_without_fake_profile_data(self):
        response = self.signup()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn("access", response.data)
        pending = PendingProgramRegistration.objects.get()
        user = pending.user
        self.assertFalse(user.is_active)
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "")
        self.assertIsNone(user.birthday)
        self.assertIsNone(user.onboarding_stage)
        self.assertIsNone(user.verification_date)
        self.assertFalse(PartnerProgramUserProfile.objects.exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Кейс-чемпионат клиента", mail.outbox[0].subject)
        self.assertIn(
            "https://championship.example.test/program-registration/", mail.outbox[0].body
        )
        self.assertNotIn("PROCOLLAB", mail.outbox[0].body)
        self.assertNotIn("procollab.ru", mail.outbox[0].body)

        token = confirmation_token(pending)
        result = self.client.post(self.root + "confirm/", {"token": token}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data["enrolled"])
        self.assertEqual(PartnerProgramUserProfile.objects.get().user_id, user.pk)
        login = self.client.post(
            "/api/token/",
            {"email": user.email, "password": self.payload()["password"]},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        self.assertIn("access", login.data)
        again = self.client.post(self.root + "confirm/", {"token": token}, format="json")
        self.assertEqual(again.status_code, 409)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + login.data["access"])
        for _ in range(2):
            enrolled = self.client.post(
                self.root, {"version": 1, "answers": {}}, format="json"
            )
            self.assertEqual(enrolled.status_code, 200, enrolled.data)
        self.assertEqual(PartnerProgramUserProfile.objects.filter(user=user).count(), 1)

    def test_existing_account_is_not_changed(self):
        user = create_user(email="known@example.test", first_name="Анна")
        before = (user.password, user.first_name, user.onboarding_stage)
        response = self.signup(email="KNOWN@example.test")
        self.assertEqual(response.status_code, 409, response.data)
        user.refresh_from_db()
        self.assertEqual((user.password, user.first_name, user.onboarding_stage), before)
        self.assertFalse(PendingProgramRegistration.objects.exists())

    def test_password_consent_and_form_version_checks_are_preserved(self):
        for changed in (
            {"repeat_password": "different-password"},
            {"password": "tiny", "repeat_password": "tiny"},
            {"accept_policy": False},
            {"accept_age": False},
            {"birthday": timezone.now().date().isoformat()},
            {"version": 2},
        ):
            with self.subTest(changed=changed):
                response = self.signup(**changed)
                self.assertIn(response.status_code, (400, 409), response.data)
                self.assertFalse(PendingProgramRegistration.objects.exists())
                self.assertFalse(
                    CustomUser.objects.filter(email=self.payload()["email"]).exists()
                )

    def test_closed_registration_does_not_create_an_account(self):
        self.program.datetime_registration_ends = timezone.now() - timedelta(seconds=1)
        self.program.save(update_fields=["datetime_registration_ends"])
        response = self.signup()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertFalse(PendingProgramRegistration.objects.exists())

    def test_password_reset_uses_client_origin_and_brand(self):
        user = create_user(email="reset@example.test", is_active=True)
        response = self.client.post(
            "/auth/reset_password/",
            {"email": user.email, "redirect_url": "https://outside.example.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            "https://championship.example.test/auth/reset_password/", mail.outbox[0].body
        )
        self.assertIn("Кейс-чемпионат клиента", mail.outbox[0].subject)
        self.assertNotIn("procollab", mail.outbox[0].body.lower())
        self.assertNotIn("outside.example.test", mail.outbox[0].body)

    def test_program_password_reset_preserves_return_context(self):
        user = create_user(email="program-reset@example.test", is_active=True)
        response = self.client.post(
            "/auth/reset_password/",
            {"email": user.email, "registration_program_id": self.program.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(
            "https://championship.example.test/program-password-reset/",
            mail.outbox[0].body,
        )
        self.assertIn(f"registration_program={self.program.pk}", mail.outbox[0].body)

    def test_normal_password_reset_keeps_its_subject_and_domain(self):
        user = create_user(email="normal-reset@example.test", is_active=True)
        with override_settings(WHITE_LABEL_ENABLED=False):
            response = self.client.post(
                "/auth/reset_password/", {"email": user.email}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(
            "https://app.procollab.ru/auth/reset_password/", mail.outbox[0].body
        )
        self.assertEqual(mail.outbox[0].subject, "Сброс пароля | Procollab")


@override_settings(**TEST_REGISTRATION_SETTINGS, **WHITE_LABEL_SETTINGS)
class WhiteLabelDemoTests(TestCase):
    def test_demo_is_disabled_by_default(self):
        with override_settings(WHITE_LABEL_DEMO_ALLOWED=False):
            with self.assertRaises(CommandError):
                call_command("seed_white_label_demo", stdout=io.StringIO())
        self.assertFalse(CustomUser.objects.exists())

    def test_demo_rejects_other_database_names_and_remote_hosts(self):
        with override_settings(WHITE_LABEL_DEMO_ALLOWED=True):
            for database in (
                {"HOST": "127.0.0.1", "NAME": "customer_database"},
                {"HOST": "database.example.test", "NAME": "procollab_white_label"},
            ):
                with self.subTest(database=database), patch.dict(
                    connection.settings_dict, database
                ):
                    with self.assertRaises(CommandError):
                        call_command("seed_white_label_demo", stdout=io.StringIO())
        self.assertFalse(CustomUser.objects.exists())

    def test_repeat_seed_preserves_accounts_and_program(self):
        # Меняются только метаданные проверки уже открытого тестового соединения.
        # Запросы остаются в транзакции текущей тестовой БД, в том числе в CI.
        with override_settings(WHITE_LABEL_DEMO_ALLOWED=True), patch.dict(
            connection.settings_dict,
            {"HOST": "127.0.0.1", "NAME": "test_procollab_white_label_seed"},
        ):
            call_command("seed_white_label_demo", stdout=io.StringIO())
            user = CustomUser.objects.get(email="leader@example.test")
            before = user.password
            call_command(
                "seed_white_label_demo",
                password="different-demo-password",
                stdout=io.StringIO(),
            )
        self.assertEqual(PartnerProgram.objects.count(), 1)
        self.assertEqual(CustomUser.objects.count(), 5)
        self.assertEqual(PartnerProgramUserProfile.objects.count(), 2)
        self.assertEqual(PartnerProgram.objects.get().program_projects.count(), 1)
        user.refresh_from_db()
        self.assertEqual(user.password, before)

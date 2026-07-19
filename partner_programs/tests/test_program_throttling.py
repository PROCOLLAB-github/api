from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from partner_programs.tests.helpers import create_partner_program


def throttle_settings(**rates):
    rest_framework = dict(settings.REST_FRAMEWORK)
    rest_framework["DEFAULT_THROTTLE_RATES"] = {
        **rest_framework.get("DEFAULT_THROTTLE_RATES", {}),
        **rates,
    }
    return rest_framework


class PartnerProgramThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.program = create_partner_program()

    @override_settings(
        REST_FRAMEWORK=throttle_settings(program_register_new="1/min")
    )
    @patch("partner_programs.services.registration.send_email.delay")
    def test_external_program_registration_post_is_scoped_throttled(
        self,
        send_email_delay,
    ):
        first_response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "email": "external-throttle-one@example.com",
                "password": "pass",
                "first_name": "External",
                "last_name": "User",
                "birthday": "01-01-1990",
            },
            format="json",
            REMOTE_ADDR="203.0.113.20",
        )
        second_response = self.client.post(
            f"/programs/{self.program.id}/register_new/",
            {
                "email": "external-throttle-two@example.com",
                "password": "pass",
                "first_name": "External",
                "last_name": "User",
                "birthday": "01-01-1990",
            },
            format="json",
            REMOTE_ADDR="203.0.113.20",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 429)
        send_email_delay.assert_called_once()

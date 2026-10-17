from copy import deepcopy

from django.test import TestCase
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from partner_programs.serializers.management import ImageFramingField
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_member,
    create_user,
)
from project_rates.tests.helpers import create_rate_expert


def framing():
    return {
        "cover": {"x": 25, "y": 70, "zoom": 1.8},
        "mobile_cover": {"x": 85, "y": 30, "zoom": 2.5},
        "logo": {"x": 0, "y": 100, "zoom": 3},
    }


class ProgramImageFramingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.program = create_partner_program()
        cls.manager = create_user(prefix="framing-manager")
        cls.program.managers.add(cls.manager)
        cls.member = create_program_member(cls.program).user
        cls.other = create_user(prefix="framing-other-manager")
        create_partner_program().managers.add(cls.other)
        cls.expert = create_rate_expert(program=cls.program)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.url = reverse(
            "partner_programs:management-settings",
            kwargs={"pk": self.program.pk, "section": "basic"},
        )

    def patch(self, **values):
        self.program.refresh_from_db()
        return self.client.patch(
            self.url,
            {"expected_updated_at": self.program.datetime_updated.isoformat(), **values},
            format="json",
        )

    def test_save_roundtrip_public_member_list_and_legacy_partial_write(self):
        result = self.patch(
            mobile_cover_image_address="https://example.com/mobile.png",
            image_framing=framing(),
        )
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["image_framing"], framing())
        self.assertEqual(
            result.data["mobile_cover_image_address"], "https://example.com/mobile.png"
        )
        for user in (None, self.manager, self.member):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                response = self.client.get(f"/programs/{self.program.pk}/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["image_framing"], framing())
                self.assertEqual(
                    response.data["mobile_cover_image_address"],
                    "https://example.com/mobile.png",
                )
        self.client.force_authenticate(self.manager)
        response = self.client.get("/programs/")
        row = next(
            row for row in response.data["results"] if row["id"] == self.program.pk
        )
        self.assertEqual(row["image_framing"], framing())
        self.assertEqual(self.patch(name="Legacy client rename").status_code, 200)
        self.program.refresh_from_db()
        self.assertEqual(self.program.image_framing, framing())

    def test_legacy_defaults_and_explicit_reset(self):
        self.program.refresh_from_db()
        self.assertEqual(self.program.image_framing, {})
        self.assertIsNone(self.program.mobile_cover_image_address)
        self.assertEqual(self.patch(image_framing=framing()).status_code, 200)
        result = self.patch(image_framing={}, mobile_cover_image_address=None)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["image_framing"], {})
        self.assertIsNone(result.data["mobile_cover_image_address"])

    def test_invalid_document_rejected_without_partial_name_or_url_update(self):
        bad_frames = [
            None,
            [],
            "bad",
            {"cover": {}},
            {**framing(), "extra": {}},
            {**framing(), "logo": None},
        ]
        for key, value in (
            ("x", -1),
            ("y", 101),
            ("zoom", 0.9),
            ("zoom", 3.1),
            ("x", True),
            ("x", 10**400),
            ("x", "50"),
            ("y", None),
        ):
            invalid = deepcopy(framing())
            invalid["logo"][key] = value
            bad_frames.append(invalid)
        original = self.program.name
        for data in bad_frames:
            with self.subTest(data=data):
                response = self.patch(name="Must not persist", image_framing=data)
                self.assertEqual(response.status_code, 400)
                self.program.refresh_from_db()
                self.assertEqual(self.program.name, original)
                self.assertEqual(self.program.image_framing, {})
        self.assertEqual(
            self.patch(mobile_cover_image_address="javascript:alert(1)").status_code, 400
        )

    def test_non_finite_values_rejected_at_field_boundary(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            data = framing()
            data["cover"]["x"] = value
            with self.assertRaises(ValidationError):
                ImageFramingField().run_validation(data)

    def test_write_permissions_and_stale_version_cover_new_fields(self):
        for user, status in (
            (None, 401),
            (self.member, 403),
            (self.expert, 403),
            (self.other, 403),
        ):
            self.client.force_authenticate(user)
            self.assertEqual(self.patch(image_framing=framing()).status_code, status)
        self.client.force_authenticate(create_user(is_staff=True))
        self.assertEqual(self.patch(image_framing=framing()).status_code, 200)
        self.client.force_authenticate(self.manager)
        self.program.refresh_from_db()
        old_version = self.program.datetime_updated.isoformat()
        self.assertEqual(self.patch(name="New version").status_code, 200)
        result = self.client.patch(
            self.url,
            {
                "expected_updated_at": old_version,
                "image_framing": {},
                "mobile_cover_image_address": "https://example.com/stale.png",
            },
            format="json",
        )
        self.assertEqual(result.status_code, 409)
        self.program.refresh_from_db()
        self.assertEqual(self.program.image_framing, framing())
        self.assertIsNone(self.program.mobile_cover_image_address)

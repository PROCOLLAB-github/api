"""Expert schema reads must not widen manager APIs or change filter payloads."""

from django.test import TestCase
from rest_framework.test import APIClient

from partner_programs.serializers import PartnerProgramFieldSerializer
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_field,
    create_program_member,
    create_user,
)
from project_rates.tests.helpers import create_rate_expert


class ProgramFilterAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.program = create_partner_program()
        cls.foreign_program = create_partner_program()
        cls.field = create_program_field(
            cls.program,
            name="track",
            field_type="select",
            options=["A", "B"],
            show_filter=True,
        )
        create_program_field(cls.program, name="private", show_filter=False)
        create_program_field(cls.foreign_program, name="foreign", show_filter=True)
        cls.manager = create_user(prefix="filter-manager")
        cls.program.managers.add(cls.manager)
        cls.expert = create_rate_expert(program=cls.program)
        cls.foreign_expert = create_rate_expert(program=cls.foreign_program)
        cls.foreign_manager = create_user(prefix="filter-foreign-manager")
        cls.foreign_program.managers.add(cls.foreign_manager)
        cls.participant = create_program_member(cls.program).user
        cls.outsider = create_user(prefix="filter-outsider")
        cls.staff = create_user(prefix="filter-staff", is_staff=True)
        cls.superuser = create_user(prefix="filter-superuser", is_superuser=True)

    def setUp(self):
        self.client = APIClient()
        self.url = f"/programs/{self.program.pk}/filters/"

    def test_access_matrix_and_unchanged_response(self):
        for user, expected in (
            (None, 401),
            (self.participant, 403),
            (self.outsider, 403),
            (self.foreign_expert, 403),
            (self.foreign_manager, 403),
            (self.expert, 200),
            (self.manager, 200),
            (self.staff, 200),
            (self.superuser, 200),
        ):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, expected, response.data)
                if expected == 200:
                    self.assertEqual(
                        response.data, [PartnerProgramFieldSerializer(self.field).data]
                    )

    def test_schema_endpoint_stays_read_only(self):
        for user in (self.expert, self.manager, self.staff, self.superuser):
            self.client.force_authenticate(user)
            for method in ("post", "patch", "put", "delete"):
                with self.subTest(user=user.pk, method=method):
                    response = getattr(self.client, method)(self.url, {}, format="json")
                    self.assertEqual(response.status_code, 405, response.data)

    def test_expert_does_not_gain_other_manager_endpoints(self):
        self.client.force_authenticate(self.expert)
        for suffix, method in (
            ("projects/", "get"),
            ("projects/filter/", "post"),
            ("export-projects/", "get"),
            ("manager-overview/", "get"),
        ):
            with self.subTest(suffix=suffix):
                response = getattr(self.client, method)(
                    f"/programs/{self.program.pk}/{suffix}"
                )
                self.assertEqual(response.status_code, 403, response.data)

    def test_missing_program_preserves_production_statuses(self):
        missing_id = self.foreign_program.pk + 1000
        for user, expected in (
            (None, 401),
            (self.participant, 403),
            (self.expert, 403),
            (self.manager, 403),
            (self.staff, 404),
            (self.superuser, 404),
        ):
            with self.subTest(user=user):
                self.client.force_authenticate(user)
                response = self.client.get(f"/programs/{missing_id}/filters/")
                self.assertEqual(response.status_code, expected, response.data)

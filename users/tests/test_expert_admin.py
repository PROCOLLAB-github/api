from django.contrib.admin.filters import RelatedFieldListFilter
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from users.models import CustomUser

from .helpers import (
    add_user_to_program,
    build_partner_program,
    build_superuser,
    build_user,
)


class ExpertAdminTests(TestCase):
    program_parameter = "user__partner_program_profiles__partner_program__id__exact"

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = build_superuser()
        cls.program = build_partner_program(name="FinFor25-26", tag="finfor")
        cls.other_program = build_partner_program(name="Другая программа", tag="other")
        cls.empty_program = build_partner_program(name="Без экспертов", tag="empty")
        cls.ivan = build_user(
            email="иван@example.com",
            first_name="Иван",
            last_name="Иванов",
            user_type=CustomUser.EXPERT,
        )
        cls.anna = build_user(
            email="anna@example.com",
            first_name="Анна",
            last_name="Смирнова",
            user_type=CustomUser.EXPERT,
        )
        cls.other_ivanov = build_user(
            email="petr@example.com",
            first_name="Пётр",
            last_name="Иванов",
            user_type=CustomUser.EXPERT,
        )
        cls.no_program = build_user(
            email="no-program@example.com",
            first_name="Ольга",
            last_name="Петрова",
            user_type=CustomUser.EXPERT,
        )
        cls.member = build_user(email="member@example.com")
        add_user_to_program(cls.ivan, cls.program)
        add_user_to_program(cls.ivan, cls.other_program)
        add_user_to_program(cls.anna, cls.program)
        add_user_to_program(cls.other_ivanov, cls.other_program)
        add_user_to_program(cls.member, cls.program)

    def setUp(self):
        self.client.force_login(self.admin_user)
        self.url = reverse("admin:users_expert_changelist")

    def changelist(self, params=None):
        response = self.client.get(self.url, params or {})
        self.assertEqual(response.status_code, 200)
        return response

    def assert_experts(self, response, users):
        # Keep a list: set equality would hide duplicate rows from a reverse JOIN.
        result = list(response.context["cl"].result_list)
        self.assertCountEqual(
            [expert.user_id for expert in result], [user.pk for user in users]
        )
        self.assertEqual(response.context["cl"].result_count, len(users))

    def test_changelist_has_standard_search_and_program_choices(self):
        with translation.override("en"):
            response = self.changelist()
            self.assertContains(response, 'id="searchbar"')
            self.assertContains(response, 'id="changelist-filter"')
            self.assertContains(response, "By partner program")
            changelist = response.context["cl"]
            program_filter = changelist.filter_specs[0]
            self.assertIsInstance(program_filter, RelatedFieldListFilter)
            choices = list(program_filter.choices(changelist))
            self.assertEqual(choices[0]["display"], "All")
            self.assertTrue(choices[0]["selected"])
            self.assertCountEqual(
                [choice["display"] for choice in choices[1:]],
                [str(self.program), str(self.other_program), str(self.empty_program)],
            )

    def test_search_first_name(self):
        self.assert_experts(self.changelist({"q": "Анна"}), [self.anna])

    def test_search_last_name(self):
        self.assert_experts(
            self.changelist({"q": "Иванов"}), [self.ivan, self.other_ivanov]
        )

    def test_search_email(self):
        self.assert_experts(self.changelist({"q": "иван@example.com"}), [self.ivan])

    def test_search_full_name_matches_terms_across_fields(self):
        # Standard admin search ANDs words across all fields, not exact full names.
        self.assert_experts(
            self.changelist({"q": "Иван Иванов"}), [self.ivan, self.other_ivanov]
        )
        self.assert_experts(self.changelist({"q": "Анна Смирнова"}), [self.anna])
        self.assert_experts(self.changelist({"q": "Анна Иванов"}), [])

    def test_search_ascii_email_is_case_insensitive(self):
        self.assert_experts(self.changelist({"q": "ANNA@EXAMPLE.COM"}), [self.anna])

    def test_search_cyrillic_is_case_insensitive_on_postgresql(self):
        # SQLite LIKE не обеспечивает полноценную регистронезависимость Unicode/кириллицы.
        # Поведение production PostgreSQL проверяется в Backend PostgreSQL CI.
        if connection.vendor != "postgresql":
            self.skipTest(
                "Регистронезависимость кириллицы проверяется только на PostgreSQL"
            )
        self.assert_experts(self.changelist({"q": "АННА СМИРНОВА"}), [self.anna])

    def test_unknown_search_is_empty(self):
        self.assert_experts(self.changelist({"q": "Несуществующий"}), [])

    def test_without_filter_all_experts_appear_once_including_without_program(self):
        self.assert_experts(
            self.changelist(), [self.ivan, self.anna, self.other_ivanov, self.no_program]
        )

    def test_program_filter_excludes_other_program_and_unregistered_experts(self):
        self.assert_experts(
            self.changelist({self.program_parameter: self.program.pk}),
            [self.ivan, self.anna],
        )

    def test_expert_registered_in_two_programs_appears_once_in_each(self):
        for program, expected in (
            (self.program, [self.ivan, self.anna]),
            (self.other_program, [self.ivan, self.other_ivanov]),
        ):
            with self.subTest(program=program.pk):
                self.assert_experts(
                    self.changelist({self.program_parameter: program.pk}), expected
                )

    def test_program_without_experts_returns_empty_results(self):
        self.assert_experts(
            self.changelist({self.program_parameter: self.empty_program.pk}), []
        )

    def test_search_and_program_filter_are_combined(self):
        self.assert_experts(
            self.changelist({self.program_parameter: self.program.pk, "q": "Иванов"}),
            [self.ivan],
        )

    def test_all_clears_only_program_filter_and_keeps_search(self):
        response = self.changelist(
            {self.program_parameter: self.program.pk, "q": "Иванов"}
        )
        changelist = response.context["cl"]
        all_choice = next(iter(changelist.filter_specs[0].choices(changelist)))
        response = self.client.get(self.url + all_choice["query_string"])
        self.assertEqual(response.status_code, 200)
        self.assert_experts(response, [self.ivan, self.other_ivanov])

    def test_nonexistent_program_is_empty(self):
        self.assert_experts(self.changelist({self.program_parameter: 999999999}), [])

    def test_invalid_program_uses_standard_admin_redirect_without_server_error(self):
        response = self.client.get(self.url, {self.program_parameter: "not-a-number"})
        self.assertRedirects(response, self.url + "?e=1")

    def test_user_column_does_not_query_once_per_expert(self):
        for params in ({}, {self.program_parameter: self.program.pk}):
            with self.subTest(params=params):
                changelist = self.changelist(params).context["cl"]
                # Clone to discard the render cache; rows and their users need one query.
                with self.assertNumQueries(1):
                    rows = list(changelist.result_list.all())
                    labels = [str(expert.user) for expert in rows]
                self.assertTrue(labels)

    def test_non_staff_cannot_access_changelist(self):
        self.client.force_login(self.ivan)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_staff_without_expert_permission_cannot_access_changelist(self):
        staff = build_user(email="staff@example.com", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

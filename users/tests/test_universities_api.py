from django.contrib import admin
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import University, UserEducation
from users.serializers import UserDetailSerializer
from .helpers import build_user


class UniversityDirectoryTests(TestCase):
    def setUp(self):
        University.objects.all().delete()
        self.client = APIClient()
        self.university = University.objects.create(
            name="Московский политехнический университет",
            aliases="Московский политех; МосПолитех",
            city="Москва",
        )

    def test_list_is_public_paginated_and_read_only(self):
        response = self.client.get("/auth/universities/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["name"], self.university.name)
        self.assertIn(
            self.client.post("/auth/universities/", {}).status_code, (401, 403, 405)
        )

    def test_search_finds_aliases_case_punctuation_and_yo(self):
        University.objects.create(name="Университет имени Пётра", aliases="ПГУ")
        for query, count in [
            ("МОСПОЛИТЕХ", 1),
            ("политех москва", 1),
            ("Петра", 1),
            ("п.г.у.", 1),
            ("нет совпадений", 0),
        ]:
            with self.subTest(query=query):
                response = self.client.get("/auth/universities/", {"search": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], count)

    def test_disabled_rows_are_hidden_and_admin_rename_updates_search(self):
        self.university.is_active = False
        self.university.save()
        self.assertEqual(self.client.get("/auth/universities/").data["count"], 0)
        self.university.is_active = True
        self.university.name = "Новое название"
        self.university.save(update_fields=("name", "is_active"))
        self.assertEqual(
            self.client.get("/auth/universities/", {"search": "новое"}).data["count"], 1
        )
        self.assertIn(University, admin.site._registry)

    def test_directory_changes_and_profile_save_preserve_legacy_values(self):
        user = build_user(email="university-legacy@example.com")
        legacy = "  Старое произвольное название вуза  "
        UserEducation.objects.create(user=user, organization_name=legacy)
        self.university.name = "Новое название"
        self.university.save()
        self.university.delete()
        self.assertEqual(user.education.get().organization_name, legacy)
        serializer = UserDetailSerializer(user, data={"city": "Москва"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(user.education.get().organization_name, legacy)
        serializer = UserDetailSerializer(
            user,
            data={
                "education": [
                    {"organization_name": legacy},
                    {"organization_name": "Школа №42"},
                ]
            },
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(
            list(user.education.values_list("organization_name", flat=True)),
            [legacy, "Школа №42"],
        )

    def test_pagination_reaches_remaining_entries(self):
        University.objects.create(name="Аграрный университет")
        first = self.client.get("/auth/universities/", {"limit": 1})
        second = self.client.get("/auth/universities/", {"limit": 1, "offset": 1})
        self.assertEqual(first.data["count"], 2)
        self.assertNotEqual(
            first.data["results"][0]["id"], second.data["results"][0]["id"]
        )

    def test_blank_custom_name_is_rejected(self):
        from users.serializers import UserEducationSerializer

        serializer = UserEducationSerializer(data={"organization_name": "   "})
        self.assertFalse(serializer.is_valid())
        self.assertIn("organization_name", serializer.errors)

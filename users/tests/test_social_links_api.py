from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import UserLink

from .helpers import build_user


class SocialLinksAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = build_user(email="social-links@example.com")
        self.client.force_authenticate(self.user)
        self.url = f"/auth/users/{self.user.id}/"

    def test_owner_creates_and_reads_typed_social_links(self):
        response = self.client.patch(
            self.url,
            {
                "social_links": {
                    "telegram": "https://t.me/anna",
                    "vk": "https://vk.com/anna",
                    "github": "https://github.com/anna",
                    "linkedin": "https://linkedin.com/in/anna",
                    "website": "https://anna.dev",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["social_links"],
            {
                "telegram": "https://t.me/anna",
                "vk": "https://vk.com/anna",
                "github": "https://github.com/anna",
                "linkedin": "https://linkedin.com/in/anna",
                "website": "https://anna.dev",
            },
        )
        self.assertEqual(
            UserLink.objects.filter(user=self.user, kind__isnull=False).count(), 5
        )

    def test_patch_updates_only_present_keys_and_null_deletes_one_link(self):
        UserLink.objects.create(
            user=self.user,
            kind=UserLink.Kind.TELEGRAM,
            link="https://t.me/old",
        )
        UserLink.objects.create(
            user=self.user,
            kind=UserLink.Kind.GITHUB,
            link="https://github.com/anna",
        )

        response = self.client.patch(
            self.url,
            {"social_links": {"telegram": None}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["social_links"], {"github": "https://github.com/anna"}
        )
        self.assertFalse(
            UserLink.objects.filter(user=self.user, kind=UserLink.Kind.TELEGRAM).exists()
        )

    def test_missing_social_links_does_not_change_typed_links(self):
        link = UserLink.objects.create(
            user=self.user,
            kind=UserLink.Kind.GITHUB,
            link="https://github.com/anna",
        )

        response = self.client.patch(self.url, {"first_name": "Анна"}, format="json")

        self.assertEqual(response.status_code, 200)
        link.refresh_from_db()
        self.assertEqual(link.link, "https://github.com/anna")

    def test_unknown_kind_is_rejected_atomically(self):
        self.user.first_name = "До изменения"
        self.user.save(update_fields=["first_name"])

        response = self.client.patch(
            self.url,
            {
                "first_name": "Не должно сохраниться",
                "social_links": {
                    "telegram": "https://t.me/anna",
                    "discord": "https://discord.com/users/anna",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("discord", response.data["social_links"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "До изменения")
        self.assertFalse(UserLink.objects.filter(user=self.user).exists())

    def test_invalid_url_is_rejected_without_partial_update(self):
        response = self.client.patch(
            self.url,
            {
                "social_links": {
                    "telegram": "not-a-url",
                    "website": "https://valid.example.com",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("telegram", response.data["social_links"])
        self.assertFalse(UserLink.objects.filter(user=self.user).exists())

    def test_duplicate_urls_are_rejected_as_validation_error(self):
        response = self.client.patch(
            self.url,
            {
                "social_links": {
                    "github": "https://example.com/anna",
                    "website": "https://example.com/anna",
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("website", response.data["social_links"])
        self.assertFalse(UserLink.objects.filter(user=self.user).exists())

    def test_legacy_links_remain_separate_and_legacy_patch_preserves_typed_links(self):
        legacy = UserLink.objects.create(
            user=self.user, link="https://legacy.example.com/profile"
        )
        typed = UserLink.objects.create(
            user=self.user,
            kind=UserLink.Kind.GITHUB,
            link="https://github.com/anna",
        )

        response = self.client.patch(
            self.url,
            {"links": ["https://legacy.example.com/new"]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserLink.objects.filter(pk=legacy.pk).exists())
        typed.refresh_from_db()
        self.assertEqual(typed.link, "https://github.com/anna")
        self.assertCountEqual(
            response.data["links"],
            ["https://legacy.example.com/new", "https://github.com/anna"],
        )
        self.assertEqual(
            response.data["social_links"], {"github": "https://github.com/anna"}
        )

        second_response = self.client.patch(
            self.url,
            {"links": response.data["links"]},
            format="json",
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            UserLink.objects.filter(
                user=self.user, link="https://github.com/anna"
            ).count(),
            1,
        )

    def test_two_legacy_links_are_allowed_but_typed_kind_is_unique(self):
        UserLink.objects.create(user=self.user, link="https://legacy.example.com/one")
        UserLink.objects.create(user=self.user, link="https://legacy.example.com/two")
        UserLink.objects.create(
            user=self.user,
            kind=UserLink.Kind.VK,
            link="https://vk.com/one",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            UserLink.objects.create(
                user=self.user,
                kind=UserLink.Kind.VK,
                link="https://vk.com/two",
            )

        self.assertEqual(
            UserLink.objects.filter(user=self.user, kind__isnull=True).count(), 2
        )

    def test_public_profile_returns_only_typed_links(self):
        UserLink.objects.create(
            user=self.user, link="https://legacy.example.com/private-shape"
        )
        UserLink.objects.create(
            user=self.user,
            kind=UserLink.Kind.LINKEDIN,
            link="https://linkedin.com/in/anna",
        )

        response = self.client.get(f"/auth/profiles/{self.user.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("links", response.data)
        self.assertEqual(
            response.data["social_links"],
            {"linkedin": "https://linkedin.com/in/anna"},
        )
        self.assertNotContains(response, "legacy.example.com")

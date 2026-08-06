from importlib import import_module

from django.apps import apps
from django.test import TestCase
from rest_framework.test import APIClient

from news.models import News
from partner_programs.models import PartnerProgramUserProfile

from .helpers import create_news_for, create_partner_program, create_user


class ProgramNewsAudienceAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="audience-manager")
        self.participant = create_user(prefix="audience-participant")
        self.outsider = create_user(prefix="audience-outsider")
        self.admin = create_user(prefix="audience-admin")
        self.admin.is_staff = True
        self.admin.save(update_fields=["is_staff"])
        self.program = create_partner_program(manager=self.manager)
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program,
            user=self.participant,
            partner_program_data={},
        )

    def test_manager_can_create_platform_news(self):
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/programs/{self.program.pk}/news/",
            {"text": "Public program news", "audience": "platform"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["audience"], News.Audience.PLATFORM)
        self.assertEqual(
            News.objects.get(pk=response.data["id"]).audience,
            News.Audience.PLATFORM,
        )

    def test_manager_can_create_participant_news(self):
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/programs/{self.program.pk}/news/",
            {
                "text": "Internal program news",
                "audience": "program_participants",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["audience"], News.Audience.PROGRAM_PARTICIPANTS)

    def test_omitted_audience_is_participant_only_for_angular_compatibility(self):
        self.client.force_authenticate(self.manager)

        response = self.client.post(
            f"/programs/{self.program.pk}/news/",
            {"text": "Legacy Angular program news"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            News.objects.get(pk=response.data["id"]).audience,
            News.Audience.PROGRAM_PARTICIPANTS,
        )

    def test_manager_can_change_program_news_audience(self):
        news = create_news_for(
            self.program,
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )
        self.client.force_authenticate(self.manager)

        response = self.client.patch(
            f"/programs/{self.program.pk}/news/{news.pk}/",
            {"audience": "platform"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        news.refresh_from_db()
        self.assertEqual(news.audience, News.Audience.PLATFORM)

    def test_outsider_cannot_create_or_change_program_news(self):
        news = create_news_for(self.program)
        self.client.force_authenticate(self.outsider)

        create_response = self.client.post(
            f"/programs/{self.program.pk}/news/",
            {"text": "Forbidden"},
            format="json",
        )
        update_response = self.client.patch(
            f"/programs/{self.program.pk}/news/{news.pk}/",
            {"audience": "program_participants"},
            format="json",
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)

    def test_participant_manager_and_admin_see_internal_news(self):
        news = create_news_for(
            self.program,
            text="Internal audience",
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )

        for user in (self.participant, self.manager, self.admin):
            with self.subTest(user=user.email):
                self.client.force_authenticate(user)
                list_response = self.client.get(f"/programs/{self.program.pk}/news/")
                detail_response = self.client.get(
                    f"/programs/{self.program.pk}/news/{news.pk}/"
                )
                self.assertEqual(list_response.status_code, 200)
                self.assertIn(
                    news.pk,
                    [item["id"] for item in list_response.data["results"]],
                )
                self.assertEqual(detail_response.status_code, 200)

    def test_outsider_cannot_discover_internal_news(self):
        internal_news = create_news_for(
            self.program,
            audience=News.Audience.PROGRAM_PARTICIPANTS,
        )
        platform_news = create_news_for(
            self.program,
            text="Public audience",
            audience=News.Audience.PLATFORM,
        )
        self.client.force_authenticate(self.outsider)

        list_response = self.client.get(f"/programs/{self.program.pk}/news/")
        detail_response = self.client.get(
            f"/programs/{self.program.pk}/news/{internal_news.pk}/"
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in list_response.data["results"]],
            [platform_news.pk],
        )
        self.assertEqual(detail_response.status_code, 404)

    def test_closed_audience_is_rejected_for_user_news(self):
        self.client.force_authenticate(self.outsider)

        response = self.client.post(
            f"/auth/users/{self.outsider.pk}/news/",
            {"text": "Invalid audience", "audience": "program_participants"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("audience", response.data)


class ProgramNewsAudienceDataMigrationTests(TestCase):
    def test_data_migration_keeps_existing_program_news_internal(self):
        program = create_partner_program(name="Migrated program")
        user = create_user(prefix="migrated-user-news")
        program_news = create_news_for(program, audience=News.Audience.PLATFORM)
        user_news = create_news_for(user)
        News.objects.filter(pk=user_news.pk).update(
            audience=News.Audience.PROGRAM_PARTICIPANTS
        )
        migration = import_module("news.migrations.0010_news_audience_newscomment")

        migration.set_existing_news_audiences(apps, None)

        program_news.refresh_from_db()
        user_news.refresh_from_db()
        self.assertEqual(
            program_news.audience,
            News.Audience.PROGRAM_PARTICIPANTS,
        )
        self.assertEqual(user_news.audience, News.Audience.PLATFORM)

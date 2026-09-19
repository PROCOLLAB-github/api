from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from news.tests.helpers import create_partner_program, create_user
from notifications.events import (
    notify_course_access_opened,
    notify_program_material_published,
    notify_program_news_published,
)
from notifications.models import Notification
from notifications.services import create_notification
from partner_programs.models import PartnerProgramUserProfile


class ProgramNotificationImageTests(TestCase):
    def setUp(self):
        self.actor = create_user(prefix="image-publisher")
        self.actor.avatar = "https://example.com/publisher.png"
        self.actor.save(update_fields=["avatar"])
        self.members = [create_user(prefix="image-member") for _ in range(2)]
        self.outsider = create_user(prefix="image-outsider")
        self.program = create_partner_program(manager=self.actor)
        self.program.image_address = "https://example.com/program.png"
        self.program.save(update_fields=["image_address"])
        for user in [self.actor, *self.members]:
            PartnerProgramUserProfile.objects.create(
                partner_program=self.program,
                user=user,
                partner_program_data={},
            )

    def events(self, suffix=1):
        """Задаёт старые ключи и маршруты независимо от реализации emitters."""
        item = SimpleNamespace(
            pk=suffix, title="Материал / курс", datetime_updated=timezone.now()
        )
        return (
            (
                notify_program_news_published,
                item,
                Notification.Type.PROGRAM_NEWS_PUBLISHED,
                "Новая публикация",
                f"В программе «{self.program.name}» появилась новость.",
                f"program-news:{suffix}:published",
                f"/office/program/{self.program.pk}",
            ),
            (
                notify_program_material_published,
                item,
                Notification.Type.PROGRAM_MATERIAL_PUBLISHED,
                "Новый материал",
                f"В программе «{self.program.name}» добавлен материал «{item.title}».",
                f"program-material:{suffix}:published",
                f"/office/program/{self.program.pk}",
            ),
            (
                notify_course_access_opened,
                item,
                Notification.Type.COURSE_ACCESS_OPENED,
                "Открыт доступ к курсу",
                f"В программе «{self.program.name}» открыт доступ к курсу «{item.title}».",
                f"course-access:{suffix}:{item.datetime_updated.isoformat()}",
                f"/office/courses/{suffix}",
            ),
        )

    def test_program_images_keep_actor_recipients_routes_keys_and_retry_snapshot(self):
        for emit, item, kind, title, message, key, url in self.events():
            with self.subTest(kind=kind):
                self.program.image_address = "https://example.com/program.png"
                emit(item, program=self.program, actor=self.actor)
                self.program.image_address = "https://example.com/replaced.png"
                emit(item, program=self.program, actor=self.actor)
                rows = Notification.objects.filter(event_key=key)
                self.assertEqual(rows.count(), 2)
                self.assertEqual(
                    set(rows.values_list("recipient_id", flat=True)),
                    {member.pk for member in self.members},
                )
                for row in rows:
                    self.assertEqual(row.image_url, "https://example.com/program.png")
                    self.assertEqual(row.actor_id, self.actor.pk)
                    self.assertEqual(row.type, kind)
                    self.assertEqual(row.category, Notification.Category.PROGRAM)
                    self.assertEqual(row.title, title)
                    self.assertEqual(row.message, message)
                    self.assertEqual(row.action_url, url)

    def test_missing_and_blank_program_image_are_stored_as_null(self):
        for index, image in enumerate((None, ""), start=1):
            self.program.image_address = image
            for emit, item, kind, _title, _message, key, _url in self.events(index):
                with self.subTest(kind=kind, image=image):
                    emit(item, program=self.program, actor=self.actor)
                    rows = Notification.objects.filter(event_key=key)
                    self.assertEqual(rows.count(), 2)
                    self.assertTrue(all(row.image_url is None for row in rows))

    def test_api_keeps_image_and_real_actor_in_list_and_mark_read(self):
        emit, item, *_ = self.events()[0]
        emit(item, program=self.program, actor=self.actor)
        client = APIClient()
        client.force_authenticate(self.members[0])
        response = client.get("/notifications/")
        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        self.assertEqual(row["image_url"], self.program.image_address)
        self.assertEqual(row["actor"]["id"], self.actor.pk)
        self.assertEqual(row["actor"]["avatar"], self.actor.avatar)
        marked = client.post(f"/notifications/{row['id']}/read/")
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.data["image_url"], row["image_url"])
        self.assertEqual(marked.data["actor"], row["actor"])

    def test_other_types_default_to_null_and_keep_actor_contract(self):
        client = APIClient()
        client.force_authenticate(self.members[0])
        for kind in (
            Notification.Type.PROJECT_INVITE_CREATED,
            Notification.Type.VACANCY_RESPONSE_CREATED,
        ):
            with self.subTest(kind=kind):
                notification = create_notification(
                    recipient_id=self.members[0].pk,
                    actor_id=self.actor.pk,
                    notification_type=kind,
                    title="Без изменений",
                    message="Без изменений",
                    action_url="/office/projects/invites",
                    event_key=f"ordinary:{kind}",
                )
                self.assertIsNone(notification.image_url)
        response = client.get("/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        for row in response.data["results"]:
            self.assertIsNone(row["image_url"])
            self.assertEqual(
                row["actor"],
                {
                    "id": self.actor.pk,
                    "first_name": self.actor.first_name,
                    "last_name": self.actor.last_name,
                    "avatar": self.actor.avatar,
                },
            )

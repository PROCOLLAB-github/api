from types import SimpleNamespace

from django.contrib import admin
from django.db import connection, transaction
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from courses.admin_config.content import CourseAdmin
from courses.models import Course, CourseContentStatus
from news.models import News
from news.services import (
    create_program_news,
    create_project_news,
    create_user_news,
)
from news.tests.helpers import create_partner_program, create_project, create_user
from notifications.events import notify_program_news_published
from notifications.models import Notification
from partner_programs.admin import PartnerProgramAdmin, PartnerProgramMaterialAdmin
from partner_programs.models import (
    PartnerProgramMaterial,
    PartnerProgramUserProfile,
)


def add_program_member(program, user):
    return PartnerProgramUserProfile.objects.create(
        partner_program=program,
        user=user,
        project=None,
        partner_program_data={},
    )


class ProgramNewsNotificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = create_user(prefix="program-notification-manager")
        self.participant = create_user(prefix="program-notification-participant")
        self.second_participant = create_user(
            prefix="program-notification-second-participant"
        )
        self.outsider = create_user(prefix="program-notification-outsider")
        self.program = create_partner_program(manager=self.manager)
        for user in (self.manager, self.participant, self.second_participant):
            add_program_member(self.program, user)
        self.client.force_authenticate(self.manager)

    def test_program_news_notifies_only_members_for_both_audiences(self):
        for index, audience in enumerate(
            (News.Audience.PROGRAM_PARTICIPANTS, News.Audience.PLATFORM),
            start=1,
        ):
            response = self.client.post(
                f"/programs/{self.program.pk}/news/",
                {"text": f"Новость {index}", "audience": audience},
                format="json",
            )

            self.assertEqual(response.status_code, 201)
            event_key = f"program-news:{response.data['id']}:published"
            notifications = Notification.objects.filter(event_key=event_key)
            self.assertEqual(
                set(notifications.values_list("recipient_id", flat=True)),
                {self.participant.pk, self.second_participant.pk},
            )
            self.assertFalse(notifications.filter(recipient=self.manager).exists())
            self.assertFalse(notifications.filter(recipient=self.outsider).exists())

            notification = notifications.get(recipient=self.participant)
            self.assertEqual(
                notification.type,
                Notification.Type.PROGRAM_NEWS_PUBLISHED,
            )
            self.assertEqual(notification.category, Notification.Category.PROGRAM)
            self.assertEqual(notification.title, "Новая новость в программе")
            self.assertEqual(
                notification.message,
                f"В программе «{self.program.name}» опубликована новая новость.",
            )
            self.assertEqual(
                notification.action_url,
                f"/office/program/{self.program.pk}",
            )
            self.assertEqual(notification.actor_id, self.manager.pk)

    def test_update_retry_and_other_news_contexts_do_not_duplicate_event(self):
        news = create_program_news(
            self.program,
            self.manager,
            {
                "text": "Исходная новость",
                "audience": News.Audience.PROGRAM_PARTICIPANTS,
            },
        )
        event_key = f"program-news:{news.pk}:published"
        initial_count = Notification.objects.filter(event_key=event_key).count()

        response = self.client.patch(
            f"/programs/{self.program.pk}/news/{news.pk}/",
            {"text": "Обновлённая новость"},
            format="json",
        )
        notify_program_news_published(
            news,
            program=self.program,
            actor=self.manager,
        )
        create_project_news(
            create_project(leader=self.manager),
            self.manager,
            {"text": "Новость проекта"},
        )
        create_user_news(
            self.manager,
            self.manager,
            {"text": "Новость пользователя"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(event_key=event_key).count(),
            initial_count,
        )
        self.assertEqual(
            Notification.objects.filter(
                type=Notification.Type.PROGRAM_NEWS_PUBLISHED
            ).count(),
            initial_count,
        )

    def test_news_and_notifications_roll_back_together(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                create_program_news(
                    self.program,
                    self.manager,
                    {"text": "Откатываемая новость"},
                )
                raise RuntimeError("rollback")

        self.assertFalse(
            News.objects.get_news(self.program)
            .filter(text="Откатываемая новость")
            .exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                type=Notification.Type.PROGRAM_NEWS_PUBLISHED
            ).exists()
        )

    def test_program_event_uses_one_recipient_query_and_one_bulk_insert(self):
        news = News.objects.add_news(self.program, text="Массовая новость")

        with CaptureQueriesContext(connection) as queries:
            notify_program_news_published(
                news,
                program=self.program,
                actor=self.manager,
            )

        data_queries = [
            query["sql"].lstrip().upper()
            for query in queries.captured_queries
            if query["sql"].lstrip().upper().startswith(("SELECT", "INSERT"))
        ]
        self.assertEqual(
            sum(sql.startswith("SELECT") for sql in data_queries),
            1,
        )
        self.assertEqual(
            sum(sql.startswith("INSERT") for sql in data_queries),
            1,
        )


class MaterialFormset:
    model = PartnerProgramMaterial

    def __init__(self, program, titles):
        self.instance = program
        self.titles = titles
        self.new_objects = []

    def save(self):
        self.new_objects = [
            PartnerProgramMaterial.objects.create(
                program=self.instance,
                title=title,
                url=f"https://example.com/{index}",
            )
            for index, title in enumerate(self.titles, start=1)
        ]
        return self.new_objects


class ProgramMaterialNotificationTests(TestCase):
    def setUp(self):
        self.actor = create_user(prefix="material-notification-actor")
        self.participant = create_user(prefix="material-notification-participant")
        self.outsider = create_user(prefix="material-notification-outsider")
        self.program = create_partner_program(manager=self.actor)
        add_program_member(self.program, self.actor)
        add_program_member(self.program, self.participant)
        self.request = RequestFactory().post("/admin/partner-program/")
        self.request.user = self.actor
        self.program_admin = PartnerProgramAdmin(self.program.__class__, admin.site)
        self.material_admin = PartnerProgramMaterialAdmin(
            PartnerProgramMaterial,
            admin.site,
        )

    def save_inline_materials(self, *titles):
        formset = MaterialFormset(self.program, titles)
        self.program_admin.save_formset(
            self.request,
            SimpleNamespace(),
            formset,
            change=True,
        )
        return formset.new_objects

    def test_inline_create_notifies_members_and_each_material_has_own_event(self):
        materials = self.save_inline_materials("Регламент")
        materials.extend(self.save_inline_materials("Шаблон", "Презентация"))

        notifications = Notification.objects.filter(
            type=Notification.Type.PROGRAM_MATERIAL_PUBLISHED
        )
        self.assertEqual(notifications.count(), 3)
        self.assertEqual(
            set(notifications.values_list("recipient_id", flat=True)),
            {self.participant.pk},
        )
        self.assertFalse(notifications.filter(recipient=self.actor).exists())
        self.assertFalse(notifications.filter(recipient=self.outsider).exists())
        self.assertEqual(
            set(notifications.values_list("event_key", flat=True)),
            {f"program-material:{material.pk}:published" for material in materials},
        )

        first = notifications.get(
            event_key=f"program-material:{materials[0].pk}:published"
        )
        self.assertEqual(first.title, "Новый материал в программе")
        self.assertEqual(
            first.message,
            f"В программе «{self.program.name}» добавлен материал «Регламент».",
        )
        self.assertEqual(first.action_url, f"/office/program/{self.program.pk}")
        self.assertEqual(first.actor_id, self.actor.pk)

    def test_update_and_delete_do_not_create_notifications(self):
        material = self.save_inline_materials("Материал")[0]
        initial_count = Notification.objects.count()

        material.title = "Обновлённый материал"
        self.material_admin.save_model(
            self.request,
            material,
            SimpleNamespace(),
            change=True,
        )
        self.material_admin.delete_model(self.request, material)

        self.assertEqual(Notification.objects.count(), initial_count)

    def test_standalone_admin_create_uses_same_event(self):
        material = PartnerProgramMaterial(
            program=self.program,
            title="Отдельный материал",
            url="https://example.com/standalone",
        )

        self.material_admin.save_model(
            self.request,
            material,
            SimpleNamespace(),
            change=False,
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.participant,
                event_key=f"program-material:{material.pk}:published",
            ).exists()
        )

    def test_failed_admin_transaction_leaves_no_material_or_notification(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.save_inline_materials("Откатываемый материал")
                raise RuntimeError("rollback")

        self.assertFalse(
            PartnerProgramMaterial.objects.filter(title="Откатываемый материал").exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                type=Notification.Type.PROGRAM_MATERIAL_PUBLISHED
            ).exists()
        )


class CourseNotificationTests(TestCase):
    def setUp(self):
        self.actor = create_user(prefix="course-notification-actor")
        self.participant = create_user(prefix="course-notification-participant")
        self.outsider = create_user(prefix="course-notification-outsider")
        self.program = create_partner_program(manager=self.actor)
        add_program_member(self.program, self.actor)
        add_program_member(self.program, self.participant)
        self.request = RequestFactory().post("/admin/courses/course/")
        self.request.user = self.actor
        self.form = SimpleNamespace(cleaned_data={})
        self.course_admin = CourseAdmin(Course, admin.site)

    def save_course(self, course, *, change):
        self.course_admin.save_model(
            self.request,
            course,
            self.form,
            change=change,
        )

    def test_create_published_course_notifies_only_program_members(self):
        course = Course(
            title="Курс программы",
            status=CourseContentStatus.PUBLISHED,
            partner_program=self.program,
        )

        self.save_course(course, change=False)

        notification = Notification.objects.get(
            type=Notification.Type.COURSE_ACCESS_OPENED
        )
        self.assertEqual(notification.recipient_id, self.participant.pk)
        self.assertEqual(notification.actor_id, self.actor.pk)
        self.assertEqual(notification.title, "Открыт доступ к курсу")
        self.assertEqual(
            notification.message,
            f"В программе «{self.program.name}» открыт доступ к курсу «{course.title}».",
        )
        self.assertEqual(notification.action_url, f"/office/courses/{course.pk}")
        self.assertFalse(Notification.objects.filter(recipient=self.outsider).exists())

    def test_publish_transition_is_idempotent_and_republish_is_new_event(self):
        course = Course.objects.create(
            title="Переходы курса",
            status=CourseContentStatus.DRAFT,
            partner_program=self.program,
        )

        course.status = CourseContentStatus.PUBLISHED
        self.save_course(course, change=True)
        self.save_course(course, change=True)
        first_event_keys = set(
            Notification.objects.filter(
                type=Notification.Type.COURSE_ACCESS_OPENED
            ).values_list("event_key", flat=True)
        )

        course.status = CourseContentStatus.DRAFT
        self.save_course(course, change=True)
        course.status = CourseContentStatus.PUBLISHED
        self.save_course(course, change=True)
        notifications = Notification.objects.filter(
            type=Notification.Type.COURSE_ACCESS_OPENED
        )

        self.assertEqual(len(first_event_keys), 1)
        self.assertEqual(notifications.count(), 2)
        self.assertEqual(
            notifications.values("event_key").distinct().count(),
            2,
        )

    def test_draft_and_programless_courses_do_not_notify(self):
        self.save_course(
            Course(
                title="Черновик",
                status=CourseContentStatus.DRAFT,
                partner_program=self.program,
            ),
            change=False,
        )
        self.save_course(
            Course(
                title="Курс без программы",
                status=CourseContentStatus.PUBLISHED,
            ),
            change=False,
        )

        self.assertFalse(
            Notification.objects.filter(
                type=Notification.Type.COURSE_ACCESS_OPENED
            ).exists()
        )

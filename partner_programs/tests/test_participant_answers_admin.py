"""Questionnaire answers on the existing Django admin profile route."""

from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape
from rest_framework.test import APIClient

from partner_programs.admin import PartnerProgramUserProfileAdmin
from partner_programs.models import PartnerProgramUserProfile, ProgramRegistration
from partner_programs.tests.helpers import (
    create_partner_program,
    create_project,
    create_user,
)
from users.models import CustomUser


def change_url(profile):
    return reverse(
        "admin:partner_programs_partnerprogramuserprofile_change", args=[profile.pk]
    )


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class ParticipantAnswersAdminTests(TestCase):
    def setUp(self):
        self.admin = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.admin)
        self.program = create_partner_program()
        self.participant = create_user(is_active=True)

    def create_profile(self, answers, schema=None, program=None):
        return PartnerProgramUserProfile.objects.create(
            partner_program=program or self.program,
            user=self.participant,
            partner_program_data=answers,
            registration_schema=schema if schema is not None else {},
        )

    def test_historical_schema_matches_frontend_and_escapes_answers(self):
        renamed, archived, choices, optional = (f"f{value:032x}" for value in range(1, 5))
        archived_label = 'Исторический вопрос <img src=x onerror="alert(1)">'
        value = "<script>alert(1)</script>\nВторая строка"
        schema = {
            "mode": "native",
            "fields": [
                {"id": renamed, "label": "Прежнее название"},
                {"id": archived, "label": archived_label},
                {"id": choices, "label": "Варианты"},
                {"id": optional, "label": "Пропущенный вопрос"},
            ],
        }
        answers = {choices: ["МГУ", "Другое: Вуз"], archived: value, renamed: 0}
        profile = self.create_profile(answers, schema)
        ProgramRegistration.objects.create(
            program=self.program,
            published={
                "mode": "native",
                "fields": [{"id": renamed, "label": "Новое имя"}],
            },
        )

        page = self.client.get(change_url(profile))
        for label in (
            "Профиль участника",
            "Ответы анкеты",
            "Участник",
            "Программа",
            "Проект",
            "Прежнее название",
            escape(archived_label),
            escape(value),
            "МГУ, Другое: Вуз",
            "Пропущенный вопрос",
        ):
            self.assertContains(page, label)
        for technical_value in (
            "Новое имя",
            renamed,
            archived,
            "<script>alert(1)</script>",
        ):
            self.assertNotContains(page, technical_value)
        for text in ("0", "—"):
            self.assertContains(
                page, f'<dd class="registration-answer-text">{text}</dd>', html=True
            )

        api = APIClient()
        api.force_authenticate(self.admin)
        response = api.get(
            reverse(
                "partner_programs:management-participants", kwargs={"pk": self.program.pk}
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"][0]["registration_answers"],
            [
                {"label": "Прежнее название", "value": 0},
                {"label": archived_label, "value": value},
                {"label": "Варианты", "value": ["МГУ", "Другое: Вуз"]},
                {"label": "Пропущенный вопрос", "value": None},
            ],
        )
        profile.refresh_from_db()
        self.assertEqual(profile.partner_program_data, answers)
        self.assertEqual(profile.registration_schema, schema)

    def test_legacy_and_unknown_answers_remain_visible(self):
        self.program.data_schema = {"city_label": {"name": "Город регистрации"}}
        self.program.save(update_fields=["data_schema"])
        published_id = "f" + "a" * 32
        ProgramRegistration.objects.create(
            program=self.program,
            published={
                "mode": "native",
                "fields": [{"id": published_id, "label": "Дата"}],
            },
        )
        unknown_key = '<img src=x onerror="alert(1)">'
        answers = {
            "city_label": "Орёл",
            published_id: "2026-11-21",
            unknown_key: {"старое": [0, False]},
        }
        profile = self.create_profile(answers, {"fields": {"corrupt": "schema"}})

        page = self.client.get(change_url(profile))
        for item in (
            "Город регистрации",
            "Орёл",
            "Дата",
            "2026-11-21",
            "Ответ без названия вопроса",
            escape(unknown_key),
            escape('{"старое": [0, false]}'),
        ):
            self.assertContains(page, item)
        self.assertNotContains(page, unknown_key)
        self.assertNotContains(page, "city_label")
        profile.refresh_from_db()
        self.assertEqual(profile.partner_program_data, answers)

    def test_non_object_and_empty_historical_answers(self):
        profile = self.create_profile(["Архивная строка", 0, False], [])
        self.assertContains(
            self.client.get(change_url(profile)),
            escape('["Архивная строка", 0, false]'),
        )
        profile.partner_program_data = {}
        profile.save(update_fields=["partner_program_data"])
        self.assertContains(
            self.client.get(change_url(profile)), "Нет сохраненных ответов."
        )

    def test_metadata_edit_ignores_posted_answers(self):
        profile = self.create_profile({"old": "Старый ответ"})
        project = create_project(leader=self.participant)

        page = self.client.get(change_url(profile))
        self.assertNotContains(page, 'name="partner_program_data"')
        response = self.client.post(
            change_url(profile),
            {
                "user": self.participant.pk,
                "partner_program": self.program.pk,
                "project": project.pk,
                "partner_program_data": '{"old": "Искаженный ответ"}',
                "_save": "Сохранить",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.project, project)
        self.assertEqual(profile.partner_program_data, {"old": "Старый ответ"})

    def test_metadata_edit_preserves_a_more_recent_answer(self):
        profile = self.create_profile({"old": "Старый ответ"})
        project = create_project(leader=self.participant)
        original_save = PartnerProgramUserProfileAdmin.save_model

        def save_after_answer_update(model_admin, request, obj, form, change):
            PartnerProgramUserProfile.objects.filter(pk=obj.pk).update(
                partner_program_data={"old": "Сохраненный более новый ответ"}
            )
            original_save(model_admin, request, obj, form, change)

        with patch.object(
            PartnerProgramUserProfileAdmin,
            "save_model",
            autospec=True,
            side_effect=save_after_answer_update,
        ):
            response = self.client.post(
                change_url(profile),
                {
                    "user": self.participant.pk,
                    "partner_program": self.program.pk,
                    "project": project.pk,
                    "_save": "Сохранить",
                },
            )
        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.project, project)
        self.assertEqual(
            profile.partner_program_data, {"old": "Сохраненный более новый ответ"}
        )

    def test_orphaned_user_and_project_do_not_hide_answers(self):
        profile = PartnerProgramUserProfile.objects.create(
            partner_program=self.program,
            user=None,
            project=None,
            partner_program_data={"historical": "Исторический ответ"},
        )
        self.assertContains(self.client.get(change_url(profile)), "Исторический ответ")

    def test_existing_staff_permissions_and_profile_visibility(self):
        profile = self.create_profile({"first": "Ответ своей программы"})
        foreign_program = create_partner_program(name="Закрытая другая программа")
        foreign = self.create_profile({"second": "Чужой ответ"}, program=foreign_program)
        manager = create_user(
            is_staff=True, is_active=True, user_type=CustomUser.EXPERT
        )
        manager.groups.add(Group.objects.create(name="Руководитель программы"))
        manager.expert.programs.add(foreign_program)
        self.program.managers.add(manager)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(change_url(profile)).status_code, 403)

        view_permission = Permission.objects.get(
            content_type__app_label="partner_programs",
            codename="view_partnerprogramuserprofile",
        )
        manager.user_permissions.add(view_permission)
        page = self.client.get(change_url(profile))
        self.assertContains(page, "Ответ своей программы")
        self.assertNotContains(page, 'name="partner_program_data"')
        self.assertEqual(self.client.post(change_url(profile), {}).status_code, 403)
        self.assertContains(self.client.get(change_url(foreign)), "Чужой ответ")
        list_page = self.client.get(
            reverse("admin:partner_programs_partnerprogramuserprofile_changelist")
        )
        self.assertContains(list_page, change_url(profile))
        self.assertContains(list_page, change_url(foreign))

        self.participant.user_permissions.add(view_permission)
        self.client.force_login(self.participant)
        self.assertEqual(self.client.get(change_url(profile)).status_code, 302)

"""Реальные запросы к админке и чтение той же анкеты через публичное API."""

import copy
import io

from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook
from rest_framework.test import APIClient

from partner_programs.models import ProgramRegistration, PartnerProgramUserProfile
from partner_programs.services import native_registration as registration
from partner_programs.tests.helpers import create_partner_program, create_user


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class RegistrationAdminTests(TestCase):
    def setUp(self):
        self.admin = create_user(is_staff=True, is_superuser=True, is_active=True)
        self.client.force_login(self.admin)
        self.program = create_partner_program(name="Программа из админки")
        self.url = reverse(
            "admin:partner_programs_partnerprogram_registration", args=[self.program.pk]
        )
        self.field = {
            "id": "f" + "a" * 32,
            "label": "Ваш вуз",
            "type": "select",
            "help_text": "Выберите вуз",
            "required": True,
            "source": "own",
            "options": ["Первый вуз", "Второй вуз"],
            "allow_other": True,
        }

    def payload(self, *, fields=None, revision=0, action="save", mode="native"):
        fields = fields if fields is not None else [self.field]
        data = {
            "mode": mode,
            "revision": revision,
            "action": action,
            "fields-TOTAL_FORMS": len(fields),
            "fields-INITIAL_FORMS": 0,
        }
        for index, field in enumerate(fields):
            for key, value in field.items():
                if isinstance(value, bool):
                    if value:
                        data[f"fields-{index}-{key}"] = "on"
                else:
                    data[f"fields-{index}-{key}"] = (
                        "\n".join(value) if isinstance(value, list) else value
                    )
            data[f"fields-{index}-ORDER"] = index + 1
        return data

    def test_program_card_links_to_russian_editor_without_creating_config(self):
        page = self.client.get(
            reverse(
                "admin:partner_programs_partnerprogram_change", args=[self.program.pk]
            )
        )
        self.assertContains(page, self.url)
        page = self.client.get(self.url)
        for label in (
            "Способ регистрации",
            "Добавить поле",
            "Опубликовать форму",
            "Короткий текст",
            "Справочник вузов",
        ):
            self.assertContains(page, label)
        self.assertFalse(ProgramRegistration.objects.exists())

    def test_create_draft_then_publish_and_enroll_via_public_api(self):
        self.assertEqual(self.client.post(self.url, self.payload()).status_code, 302)
        config = ProgramRegistration.objects.get(program=self.program)
        self.assertIsNone(config.published)
        api = APIClient()
        api.force_authenticate(self.admin)
        state = api.get(f"/programs/{self.program.pk}/management/registration/").data
        self.assertEqual(state["draft"]["fields"], [self.field])
        self.assertEqual(
            self.client.post(
                self.url, self.payload(revision=1, action="publish")
            ).status_code,
            302,
        )
        config.refresh_from_db()
        self.assertEqual(config.published_version, 1)
        self.assertEqual(config.published["fields"], [self.field])
        public = api.get(f"/programs/{self.program.pk}/registration/")
        self.assertEqual(public.status_code, 200, public.data)
        member = create_user(is_active=True)
        api.force_authenticate(member)
        response = api.post(
            f"/programs/{self.program.pk}/registration/",
            {
                "version": config.published_version,
                "answers": {self.field["id"]: "Первый вуз"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(
            PartnerProgramUserProfile.objects.filter(
                partner_program=self.program, user=member
            ).exists()
        )

    def test_empty_questionnaire_can_publish(self):
        self.assertEqual(
            self.client.post(
                self.url, self.payload(fields=[], action="publish")
            ).status_code,
            302,
        )
        self.assertEqual(
            ProgramRegistration.objects.get(program=self.program).published,
            {"mode": "native", "fields": []},
        )

    def test_all_field_types_and_directory_sources_publish_without_json_editing(self):
        fields = []
        for index, kind in enumerate(
            ("text", "textarea", "number", "date", "select", "multiselect")
        ):
            fields.append(
                {
                    **self.field,
                    "id": "f" + str(index) * 32,
                    "type": kind,
                    "source": "regions"
                    if kind == "select"
                    else "universities"
                    if kind == "multiselect"
                    else "own",
                    "options": [],
                    "allow_other": kind in ("select", "multiselect"),
                }
            )
        self.assertEqual(
            self.client.post(
                self.url, self.payload(fields=fields, action="publish")
            ).status_code,
            302,
        )
        self.assertEqual(
            ProgramRegistration.objects.get(program=self.program).published["fields"],
            fields,
        )

    def test_more_than_100_fields_cannot_be_saved(self):
        fields = [{**self.field, "id": "f" + format(i, "032x")} for i in range(101)]
        page = self.client.post(self.url, self.payload(fields=fields))
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["fields"].non_form_errors())
        self.assertFalse(ProgramRegistration.objects.exists())

    def test_preview_and_add_do_not_save_or_enroll(self):
        page = self.client.post(self.url, self.payload(action="preview"))
        self.assertContains(page, "Предпросмотр анкеты участника")
        self.assertContains(page, "Первый вуз")
        self.assertContains(page, "disabled")
        self.assertFalse(ProgramRegistration.objects.exists())
        self.assertFalse(PartnerProgramUserProfile.objects.exists())
        page = self.client.post(self.url, self.payload(action="add"))
        self.assertEqual(len(page.context["fields"].forms), 2)
        self.assertFalse(ProgramRegistration.objects.exists())

    def test_stale_admin_form_cannot_overwrite_frontend_update(self):
        registration.save_settings(
            self.program.pk,
            self.admin,
            {
                "revision": 0,
                "draft": {"mode": "native", "fields": []},
            },
        )
        page = self.client.post(self.url, self.payload(action="publish"))
        self.assertContains(page, "Анкета изменена другим организатором")
        config = ProgramRegistration.objects.get(program=self.program)
        self.assertEqual(config.revision, 1)
        self.assertEqual(config.draft["fields"], [])
        self.assertIsNone(config.published)

    def test_missing_options_can_save_but_not_publish(self):
        field = {**self.field, "options": []}
        self.assertEqual(
            self.client.post(self.url, self.payload(fields=[field])).status_code, 302
        )
        page = self.client.post(
            self.url, self.payload(fields=[field], revision=1, action="publish")
        )
        self.assertContains(page, "Добавьте варианты ответа")
        config = ProgramRegistration.objects.get(program=self.program)
        self.assertIsNone(config.published)
        self.assertEqual(config.revision, 1)

    def test_duplicate_field_ids_and_invalid_sources_are_rejected(self):
        for fields in ([self.field, self.field], [{**self.field, "source": "regions"}]):
            with self.subTest(fields=fields):
                self.assertEqual(
                    self.client.post(self.url, self.payload(fields=fields)).status_code,
                    200,
                )
                self.assertFalse(ProgramRegistration.objects.exists())

    def test_reorder_and_delete_preserve_published_snapshot_and_answers(self):
        other = {**self.field, "id": "f" + "b" * 32, "label": "Второй вопрос"}
        schema = {"mode": "native", "fields": [self.field, other]}
        config = ProgramRegistration.objects.create(
            program=self.program,
            draft=schema,
            published=copy.deepcopy(schema),
            published_version=1,
        )
        member = create_user()
        profile = PartnerProgramUserProfile.objects.create(
            partner_program=self.program,
            user=member,
            partner_program_data={self.field["id"]: "Первый вуз"},
            registration_schema=copy.deepcopy(schema),
        )
        data = self.payload(fields=[self.field, other])
        data["fields-0-DELETE"] = "on"
        page = self.client.post(self.url, data)
        self.assertContains(page, "Подтвердите их архивирование")
        config.refresh_from_db()
        self.assertEqual(config.revision, 0)
        data["confirm_archive"] = "on"
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        config.refresh_from_db()
        self.assertEqual(config.draft["fields"], [other])
        self.assertEqual(config.published, schema)
        profile.refresh_from_db()
        self.assertEqual(profile.partner_program_data, {self.field["id"]: "Первый вуз"})
        self.assertEqual(profile.registration_schema, schema)
        data = self.payload(fields=[self.field, other], revision=1)
        data["fields-0-ORDER"], data["fields-1-ORDER"] = 2, 1
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        config.refresh_from_db()
        self.assertEqual(
            [f["id"] for f in config.draft["fields"]], [other["id"], self.field["id"]]
        )

    def test_csv_and_xlsx_import_preview_and_save(self):
        book = Workbook()
        for value in ("Первый", "Второй", "Первый"):
            book.active.append([value])
        stream = io.BytesIO()
        book.save(stream)
        for filename, content in (
            ("варианты.csv", "Первый\nВторой\nПервый".encode()),
            ("варианты.xlsx", stream.getvalue()),
        ):
            with self.subTest(filename=filename):
                data = self.payload(action="import")
                data["fields-0-options_file"] = SimpleUploadedFile(filename, content)
                page = self.client.post(self.url, data)
                self.assertEqual(
                    page.context["fields"].forms[0].initial["options"], "Первый\nВторой"
                )
                self.assertContains(page, "Импортировано вариантов: 2")
                self.assertFalse(ProgramRegistration.objects.exists())
        data = self.payload()
        data["fields-0-options_file"] = SimpleUploadedFile("варианты.csv", b"A\nB")
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(
            ProgramRegistration.objects.get(program=self.program).draft["fields"][0][
                "options"
            ],
            ["A", "B"],
        )

    def test_invalid_import_does_not_save(self):
        data = self.payload()
        data["fields-0-options_file"] = SimpleUploadedFile("variants.csv", b"A,B\nC,D")
        self.assertContains(self.client.post(self.url, data), "Не удалось прочитать файл")
        self.assertFalse(ProgramRegistration.objects.exists())

    def test_draft_program_and_form_publish_together_or_roll_back(self):
        self.program.draft = True
        self.program.description = ""
        self.program.save()
        page = self.client.post(self.url, self.payload(action="publish"))
        self.assertContains(page, "Заполните название и описание программы")
        self.assertFalse(ProgramRegistration.objects.exists())
        self.program.refresh_from_db()
        self.assertTrue(self.program.draft)
        self.program.description = "Описание программы"
        self.program.save()
        self.assertEqual(
            self.client.post(self.url, self.payload(action="publish")).status_code, 302
        )
        self.program.refresh_from_db()
        self.assertFalse(self.program.draft)
        self.assertEqual(
            ProgramRegistration.objects.get(program=self.program).published_version, 1
        )

    def test_external_form_requires_connection_and_then_publishes(self):
        page = self.client.post(
            self.url, self.payload(fields=[], mode="external", action="publish")
        )
        self.assertContains(page, "Дождитесь подключения внешней формы")
        self.assertFalse(ProgramRegistration.objects.exists())
        ProgramRegistration.objects.create(
            program=self.program,
            draft={"mode": "external", "fields": []},
            external_status="connected",
            external_url="https://example.test/register",
        )
        self.assertEqual(
            self.client.post(
                self.url, self.payload(fields=[], mode="external", action="publish")
            ).status_code,
            302,
        )
        page = self.client.get(self.url)
        self.assertContains(page, "https://example.test/register")

    def test_connection_request_is_shared_with_frontend_and_deduplicated(self):
        data = {
            "action": "request_connection",
            "url": "https://example.test",
            "contact": "Контакт",
            "comment": "Подключите форму",
        }
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        config = ProgramRegistration.objects.get(program=self.program)
        self.assertEqual(config.external_status, "requested")
        self.assertEqual(config.connection_requests.count(), 1)
        self.assertEqual(config.revision, 1)

    def test_staff_without_permission_and_non_staff_cannot_edit(self):
        for staff, status in ((True, 403), (False, 302)):
            user = create_user(is_active=True, is_staff=staff)
            self.client.force_login(user)
            self.assertEqual(
                self.client.post(self.url, self.payload()).status_code, status
            )
        self.assertFalse(ProgramRegistration.objects.exists())

    def test_program_manager_group_can_only_edit_allowed_programs(self):
        manager = create_user(is_staff=True, is_active=True)
        manager.groups.add(Group.objects.create(name="Руководитель программы"))
        manager.user_permissions.add(
            Permission.objects.get(codename="change_partnerprogram")
        )
        self.program.managers.add(manager)
        other = create_partner_program()
        self.client.force_login(manager)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(
            self.client.post(self.url, self.payload(action="publish")).status_code, 302
        )
        other_url = reverse(
            "admin:partner_programs_partnerprogram_registration", args=[other.pk]
        )
        self.assertEqual(self.client.post(other_url, self.payload()).status_code, 404)

    def test_csrf_required_for_editor(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url, self.payload()).status_code, 403)

    def test_connection_admin_is_russian_and_advances_editor_revision(self):
        config = ProgramRegistration.objects.create(
            program=self.program, draft={"mode": "external", "fields": []}
        )
        url = reverse(
            "admin:partner_programs_programregistration_change", args=[config.pk]
        )
        page = self.client.get(url)
        for text in (
            "Регистрация программы",
            "Статус подключения внешней формы",
            "Не подключена",
            "Редактировать анкету регистрации",
        ):
            self.assertContains(page, text)
        response = self.client.post(
            url,
            {
                "external_status": "connected",
                "external_url": "https://example.test/register",
                "connection_comment": "",
                "_save": "Сохранить",
            },
        )
        self.assertEqual(response.status_code, 302)
        config.refresh_from_db()
        self.assertEqual(config.revision, 1)
        self.assertContains(
            self.client.post(self.url, self.payload(action="publish")),
            "Анкета изменена другим организатором",
        )

    def test_admin_language_is_russian_and_public_api_keeps_its_language(self):
        from django.utils import translation

        with translation.override("en"):
            page = self.client.get(self.url)
            self.assertEqual(page["Content-Language"], "ru")
            self.assertContains(page, 'lang="ru"')
            data = self.payload()
            data["fields-0-label"] = ""
            self.assertContains(self.client.post(self.url, data), "Обязательное поле")
            self.assertEqual(translation.get_language(), "en")
            public = self.client.get(f"/programs/{self.program.pk}/registration/")
            self.assertNotEqual(public.get("Content-Language"), "ru")

    def test_new_program_created_in_admin_assigns_creator_as_manager(self):
        from partner_programs.models import PartnerProgram

        url = reverse("admin:partner_programs_partnerprogram_add")
        page = self.client.get(url)
        data = {
            "name": "Создана администратором",
            "tag": "test",
            "description": "Описание",
            "city": "Москва",
            "projects_availability": "all_users",
            "data_schema": '{"extra": {"name": "Поле"}}',
            "draft": "on",
            "_save": "Сохранить",
        }
        for inline in page.context["inline_admin_formsets"]:
            prefix = inline.formset.prefix
            data.update({f"{prefix}-TOTAL_FORMS": 0, f"{prefix}-INITIAL_FORMS": 0})
        response = self.client.post(url, data)
        errors = (
            response.context["adminform"].form.errors
            if response.status_code == 200
            else None
        )
        self.assertEqual(response.status_code, 302, errors)
        program = PartnerProgram.objects.get(name=data["name"])
        self.assertEqual(program.created_by, self.admin)
        self.assertTrue(program.managers.filter(pk=self.admin.pk).exists())

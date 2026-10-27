"""Выдача отдельного права из карточки пользователя и его использование на фронте."""

from datetime import date, datetime

from django import forms
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from users.models import CustomUser
from users.tests.helpers import build_specialization, build_superuser, build_user


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class ProgramCreationPermissionAdminTests(TestCase):
    def setUp(self):
        self.admin = build_superuser()
        self.user = build_user(v2_speciality=build_specialization())
        self.permission = Permission.objects.get(
            content_type__app_label="partner_programs", codename="add_partnerprogram"
        )
        self.other = Permission.objects.get(
            content_type__app_label="auth", codename="view_permission"
        )
        self.user.user_permissions.add(self.other)
        self.client.force_login(self.admin)
        self.url = reverse("admin:users_customuser_change", args=[self.user.pk])

    def page_and_payload(self):
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        form = page.context["adminform"].form
        data = {"_save": "Сохранить"}
        for name, field in form.fields.items():
            value = form[name].value()
            if isinstance(field.widget, forms.MultiWidget):
                for index, part in enumerate(field.widget.decompress(value)):
                    data[f"{name}_{index}"] = str(part) if part is not None else ""
            elif isinstance(field, forms.BooleanField):
                if value:
                    data[name] = "on"
            elif isinstance(field, forms.ModelMultipleChoiceField):
                data[name] = ",".join(str(item) for item in (value or []))
            elif isinstance(value, datetime):
                data[name] = value.isoformat()
            elif isinstance(value, date):
                data[name] = value.isoformat()
            else:
                data[name] = value if value is not None else ""
        for inline in page.context["inline_admin_formsets"]:
            prefix = inline.formset.prefix
            data.update({f"{prefix}-TOTAL_FORMS": 0, f"{prefix}-INITIAL_FORMS": 0})
        return page, data

    def save(self, **changes):
        _, data = self.page_and_payload()
        data.update(changes)
        response = self.client.post(self.url, data)
        errors = response.context["adminform"].form.errors if response.status_code == 200 else None
        self.assertEqual(response.status_code, 302, errors)
        self.user = CustomUser.objects.get(pk=self.user.pk)

    def capability(self):
        api = APIClient()
        api.force_authenticate(CustomUser.objects.get(pk=self.user.pk))
        response = api.get("/programs/capabilities/")
        self.assertEqual(response.status_code, 200)
        return response.data["can_create_program"]

    def test_checkbox_and_access_labels_are_russian_and_permission_is_not_duplicated(self):
        self.user.user_permissions.add(self.permission)
        page, _ = self.page_and_payload()
        form = page.context["adminform"].form
        for text in (
            "Может создавать программы", "Доступ к админке", "Все права (суперпользователь)",
            "Группы доступа", "Другие разрешения",
        ):
            self.assertContains(page, text)
        self.assertTrue(form["can_create_programs"].value())
        self.assertFalse(form.fields["user_permissions"].queryset.filter(pk=self.permission.pk).exists())
        self.assertNotIn(self.permission.pk, form["user_permissions"].value())

    def test_grant_and_revoke_change_frontend_capability_without_other_privileges(self):
        self.assertFalse(self.capability())
        self.save(can_create_programs="on")
        self.assertTrue(self.capability())
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(set(self.user.user_permissions.all()), {self.other, self.permission})
        self.save(can_create_programs="")
        self.assertFalse(self.capability())
        self.assertEqual(set(self.user.user_permissions.all()), {self.other})

    def test_unrelated_save_preserves_existing_direct_permission(self):
        self.user.user_permissions.add(self.permission)
        self.save(about_me="Описание пользователя")
        self.assertTrue(self.capability())
        self.assertEqual(set(self.user.user_permissions.all()), {self.other, self.permission})

    def test_invalid_user_form_does_not_grant_permission(self):
        _, data = self.page_and_payload()
        data.update(can_create_programs="on", email="неверный адрес")
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.assertFalse(self.capability())
        self.assertEqual(set(self.user.user_permissions.all()), {self.other})

    def test_new_user_can_receive_permission_from_checkbox(self):
        self.url = reverse("admin:users_customuser_add")
        _, data = self.page_and_payload()
        data.update(
            email="new-creator@example.com", first_name="Анна", last_name="Иванова",
            password="local-test-password", birthday="2000-01-01", user_type=CustomUser.MEMBER,
            v2_speciality=self.user.v2_speciality_id, can_create_programs="on",
        )
        response = self.client.post(self.url, data)
        errors = response.context["adminform"].form.errors if response.status_code == 200 else None
        self.assertEqual(response.status_code, 302, errors)
        created = CustomUser.objects.get(email=data["email"])
        self.assertEqual(set(created.user_permissions.all()), {self.permission})
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_group_permission_is_explained_and_does_not_become_a_direct_grant(self):
        group = Group.objects.create(name="Создатели программ")
        group.permissions.add(self.permission)
        self.user.groups.add(group)
        page, data = self.page_and_payload()
        checkbox = page.context["adminform"].form.fields["can_create_programs"]
        self.assertTrue(checkbox.disabled)
        self.assertContains(page, "Право выдано через группу доступа")
        data["can_create_programs"] = ""
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertTrue(self.capability())
        self.assertEqual(set(self.user.user_permissions.all()), {self.other})
        self.save(groups="")
        self.assertFalse(self.capability())

    def test_group_does_not_remove_an_existing_direct_grant(self):
        group = Group.objects.create(name="Создатели программ")
        group.permissions.add(self.permission)
        self.user.groups.add(group)
        self.user.user_permissions.add(self.permission)
        self.save(about_me="Описание")
        self.assertEqual(set(self.user.user_permissions.all()), {self.other, self.permission})

    def test_new_group_grant_keeps_permission_in_the_group(self):
        group = Group.objects.create(name="Создатели программ")
        group.permissions.add(self.permission)
        self.save(groups=str(group.pk), can_create_programs="")
        self.assertTrue(self.capability())
        self.assertEqual(set(self.user.user_permissions.all()), {self.other})

    def test_superuser_permission_is_explained_without_creating_a_direct_grant(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        page, _ = self.page_and_payload()
        self.assertTrue(page.context["adminform"].form.fields["can_create_programs"].disabled)
        self.assertContains(page, "Создание программ доступно благодаря статусу суперпользователя")
        self.save(about_me="Описание")
        self.assertEqual(set(self.user.user_permissions.all()), {self.other})
        self.save(is_superuser="")
        self.assertFalse(self.capability())

    def test_permission_cannot_be_edited_through_both_controls(self):
        _, data = self.page_and_payload()
        data["user_permissions"] = f"{self.other.pk},{self.permission.pk}"
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("user_permissions", response.context["adminform"].form.errors)
        self.assertFalse(self.capability())

    def test_staff_without_user_change_permission_cannot_grant(self):
        staff = build_user(email="staff@example.com", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(self.url, {"can_create_programs": "on"}).status_code, 403)
        self.assertFalse(self.capability())

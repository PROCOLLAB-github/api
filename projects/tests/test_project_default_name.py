from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from projects.models import Project
from projects.names import DEFAULT_PROJECT_NAME

from .helpers import create_user


class ProjectDefaultNameTests(TestCase):
    def setUp(self):
        self.user = create_user(prefix="default-project-name")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_model_creation_defaults_missing_and_blank_names(self):
        for payload in ({}, {"name": None}, {"name": ""}, {"name": " \t\r\n\u00a0"}):
            with self.subTest(payload=payload):
                project = Project.objects.create(leader=self.user, **payload)
                project.refresh_from_db()
                self.assertEqual(project.name, DEFAULT_PROJECT_NAME)

    def test_create_api_returns_persisted_name_in_detail_and_leader_list(self):
        for payload in ({}, {"name": None}, {"name": ""}, {"name": " \t\n"}):
            with self.subTest(payload=payload):
                response = self.client.post("/projects/", payload, format="json")
                self.assertEqual(response.status_code, 201)
                project_id = response.data["id"]
                self.assertEqual(response.data["name"], DEFAULT_PROJECT_NAME)
                self.assertEqual(
                    Project.objects.get(pk=project_id).name, DEFAULT_PROJECT_NAME
                )
                detail = self.client.get(f"/projects/{project_id}/")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.data["name"], DEFAULT_PROJECT_NAME)

        response = self.client.get("/auth/users/projects/leader/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 4)
        self.assertTrue(
            all(item["name"] == DEFAULT_PROJECT_NAME for item in response.data["results"])
        )

    def test_update_api_defaults_cleared_name_and_allows_renaming(self):
        project = Project.objects.create(leader=self.user, name="Именованный проект")
        for name in (None, "", " \t\n", "Новое название"):
            with self.subTest(name=name):
                response = self.client.put(
                    f"/projects/{project.pk}/",
                    {"name": name, "draft": True},
                    format="json",
                )
                self.assertEqual(response.status_code, 200)
                expected_name = name if name == "Новое название" else DEFAULT_PROJECT_NAME
                self.assertEqual(response.data["name"], expected_name)
                project.refresh_from_db()
                self.assertEqual(project.name, expected_name)

    def test_normalization_does_not_bypass_other_publication_validation(self):
        project = Project.objects.create(leader=self.user, name="Название")
        response = self.client.put(
            f"/projects/{project.pk}/",
            {"name": "", "description": "", "draft": False},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("description", response.data)

    def test_published_default_name_is_searchable(self):
        project = Project.objects.create(leader=self.user)
        response = self.client.put(
            f"/projects/{project.pk}/",
            {"name": "", "description": "Описание проекта", "draft": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], DEFAULT_PROJECT_NAME)
        search = self.client.get("/projects/", {"name__contains": "без названия"})
        self.assertEqual(search.status_code, 200)
        self.assertEqual([item["id"] for item in search.data["results"]], [project.pk])

    def test_partial_model_save_persists_default_for_legacy_blank_name(self):
        project = Project.objects.create(leader=self.user, name="Название")
        Project.objects.filter(pk=project.pk).update(name=None)
        project.refresh_from_db()
        project.description = "Обновлённое описание"
        project.save(update_fields=["description"])
        project.refresh_from_db()
        self.assertEqual(project.name, DEFAULT_PROJECT_NAME)
        self.assertEqual(project.description, "Обновлённое описание")

    def test_model_preserves_nonempty_name(self):
        project = Project.objects.create(leader=self.user, name="  Мой проект  ")
        project.refresh_from_db()
        self.assertEqual(project.name, "  Мой проект  ")

    def test_migration_fills_existing_blanks_without_signals_or_timestamp_changes(self):
        if connection.vendor == "postgresql":
            # C collation does not classify NBSP as whitespace; migration must still fill it.
            with connection.cursor() as cursor:
                cursor.execute(
                    'ALTER TABLE projects_project ALTER COLUMN name TYPE varchar(256) COLLATE "C"'
                )

        projects = []
        for name in (
            None,
            "",
            " \t\r\n",
            "\u00a0",
            "\u2003",
            "\x1c\x85\u2007\u202f",
            "  Название  ",
        ):
            project = Project.objects.create(leader=self.user, name="До миграции")
            Project.objects.filter(pk=project.pk).update(name=name)
            projects.append((project, name, project.datetime_updated))

        migration = import_module("projects.migrations.0034_default_project_name")
        with patch("projects.models.Project.save") as save:
            migration.fill_unnamed_projects(apps, SimpleNamespace(connection=connection))
            # Reapplying the cleanup must leave names and timestamps unchanged.
            migration.fill_unnamed_projects(apps, SimpleNamespace(connection=connection))
            save.assert_not_called()

        for project, name, updated_at in projects:
            with self.subTest(name=name):
                project.refresh_from_db()
                self.assertEqual(
                    project.name,
                    name if name and name.strip() else DEFAULT_PROJECT_NAME,
                )
                self.assertEqual(project.datetime_updated, updated_at)

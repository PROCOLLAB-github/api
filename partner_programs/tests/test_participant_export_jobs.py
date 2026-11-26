from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from partner_programs.models import ParticipantExportJob
from partner_programs.services.participant_export_jobs import (
    delete_expired_exports,
    process_export_job,
)
from partner_programs.tests.helpers import create_partner_program, create_program_member, create_user


class ParticipantExportJobTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = create_user()
        cls.other = create_user()
        cls.program = create_partner_program()
        cls.program.managers.add(cls.owner, cls.other)
        cls.member = create_program_member(
            cls.program, user=create_user(city="Москва"), data={"team": "=1+1"}
        )
        cls.member.registration_schema = {
            "fields": [{"id": "team", "label": "Название команды на момент регистрации"}]
        }
        cls.member.save(update_fields=["registration_schema"])
        cls.unfiltered = create_program_member(cls.program, user=create_user(city="Казань"))
        cls.foreign = create_program_member(create_partner_program())
        cls.root = f"/programs/{cls.program.pk}/management/participants/"
        cls.jobs = cls.root + "export-jobs/"

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_enqueues_after_commit_and_keeps_both_excel_sheets(self):
        filters = {"region_scope": "selected", "region": "Москва", "limit": 1}
        with patch("partner_programs.services.participant_export_jobs.dispatch_export") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                created = self.client.post(self.jobs, {"query": filters}, format="json")
                self.assertEqual(created.status_code, 202, created.data)
                self.assertEqual(created.data["status"], "queued")
                dispatch.assert_not_called()
                duplicate = self.client.post(
                    self.jobs, {"query": {**filters, "offset": 1, "limit": 99}}, format="json"
                )
                self.assertEqual(duplicate.data["id"], created.data["id"])
            dispatch.assert_called_once()

        url = self.jobs + created.data["id"] + "/"
        self.assertEqual(self.client.get(self.jobs).data["job"], created.data)
        self.assertEqual(self.client.get(url + "download/").status_code, 409)
        self.assertTrue(process_export_job(created.data["id"]))
        self.assertTrue(process_export_job(created.data["id"]))  # Broker redelivery.
        self.assertEqual(self.client.get(url).data["status"], "ready")
        result = self.client.get(url + "download/")
        reference = self.client.get(self.root + "export/", filters)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result["Content-Disposition"], reference["Content-Disposition"])
        self.assertEqual(result["Content-Type"], reference["Content-Type"])
        self.assertEqual(result["Cache-Control"], "private, no-store")
        with BytesIO(result.content) as actual, BytesIO(reference.content) as original:
            actual_book = load_workbook(actual)
            original_book = load_workbook(original)
            self.addCleanup(actual_book.close)
            self.addCleanup(original_book.close)
            self.assertEqual(actual_book.sheetnames, ["Участники", "Анкеты"])
            for sheet_name in actual_book.sheetnames:
                sheet, expected = actual_book[sheet_name], original_book[sheet_name]
                self.assertEqual(list(sheet.values), list(expected.values))
                self.assertEqual(sheet.freeze_panes, expected.freeze_panes)
                self.assertEqual(sheet.auto_filter.ref, expected.auto_filter.ref)
            self.assertEqual(actual_book["Участники"].max_row, 2)
            self.assertEqual(actual_book["Анкеты"]["C2"].value, "Название команды на момент регистрации")
            self.assertEqual(actual_book["Анкеты"]["D2"].value, "=1+1")
            self.assertEqual(actual_book["Анкеты"]["D2"].data_type, "s")

    def test_scope_selection_rights_and_expiration(self):
        response = self.client.post(self.jobs, {"ids": [self.foreign.pk]}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ParticipantExportJob.objects.count(), 0)
        response = self.client.post(self.jobs, {"ids": [self.unfiltered.pk]}, format="json")
        self.assertEqual(response.status_code, 202)
        pending = response.data["id"]
        url = self.jobs + pending + "/"
        self.assertEqual(self.client.post(self.jobs, {"query": {}}, format="json").status_code, 409)
        self.client.force_authenticate(self.other)
        self.assertIsNone(self.client.get(self.jobs).data["job"])
        self.assertEqual(self.client.get(url + "download/").status_code, 404)
        self.client.force_authenticate(self.owner)
        self.program.managers.remove(self.owner)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertTrue(process_export_job(pending))
        self.assertEqual(ParticipantExportJob.objects.get(pk=pending).status, "failed")
        self.program.managers.add(self.owner)
        ParticipantExportJob.objects.filter(pk=pending).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get(url).data["status"], "expired")
        self.assertEqual(self.client.get(url + "download/").status_code, 409)
        delete_expired_exports()
        self.assertEqual(self.client.get(url).status_code, 404)

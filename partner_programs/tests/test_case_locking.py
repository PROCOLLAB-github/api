"""Real PostgreSQL connections verify locks, not SQLite's no-op FOR UPDATE."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import OperationalError, connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import ValidationError

from partner_programs.models import PartnerProgramField, PartnerProgramFieldValue
from partner_programs.services.case_fields import validate_case_before_submission
from partner_programs.services.project_fields import (
    submit_program_project,
    update_program_link_fields,
)
from partner_programs.tests.helpers import (
    create_partner_program,
    create_program_project,
    create_project,
    create_user,
)
from partner_programs.tests.test_case_fields import create_case_field


@skipUnless(connection.vendor == "postgresql", "Requires real PostgreSQL row locks")
class ProgramCaseLockingTests(TransactionTestCase):
    def setUp(self):
        self.user = create_user()
        self.program = create_partner_program(is_competitive=True)
        self.link = create_program_project(
            self.program, project=create_project(leader=self.user)
        )
        self.field = create_case_field(self.program)
        self.value = PartnerProgramFieldValue.objects.create(
            program_project=self.link, field=self.field, value_text="B"
        )

    def run_while_locked(self, worker, concurrent_write):
        """Worker signals after acquiring locks; competing connection must time out."""
        entered, release = Event(), Event()

        def run():
            try:
                worker(entered, release)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            try:
                self.assertTrue(entered.wait(10), "Worker did not reach locked state")
                with self.assertRaises(OperationalError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '200ms'")
                    concurrent_write()
            finally:
                release.set()
                future.result(timeout=10)

    def test_submit_blocks_concurrent_put_then_rejects_edit_after_commit(self):
        def worker(entered, release):
            def validated(link):
                validate_case_before_submission(link)
                entered.set()
                if not release.wait(10):
                    raise AssertionError("Lock release timed out")

            with patch(
                "partner_programs.services.project_fields.validate_case_before_submission",
                side_effect=validated,
            ):
                submit_program_project(self.link.pk, self.user)

        def edit():
            update_program_link_fields(
                self.link.pk, self.user, [{"field_id": self.field.pk, "value_text": "C"}]
            )

        self.run_while_locked(worker, edit)
        with self.assertRaises(ValidationError):
            edit()
        self.value.refresh_from_db()
        self.link.refresh_from_db()
        self.assertEqual(self.value.value_text, "B")
        self.assertTrue(self.link.submitted)

    def test_case_choice_blocks_option_removal_then_history_validation_rejects_it(self):
        def worker(entered, release):
            value = PartnerProgramFieldValue.objects.get(pk=self.value.pk)
            value.value_text = "C"
            original_clean = value.clean

            def validated():
                original_clean()
                entered.set()
                if not release.wait(10):
                    raise AssertionError("Lock release timed out")

            value.clean = validated
            value.save()

        def remove_option():
            self.field.options = "A|B"
            self.field.save()

        self.run_while_locked(worker, remove_option)
        with self.assertRaises(DjangoValidationError):
            remove_option()
        self.value.refresh_from_db()
        self.field.refresh_from_db()
        self.assertEqual(self.value.value_text, "C")
        self.assertIn("C", self.field.get_options_list())

    def test_option_removal_blocks_selection_then_current_options_are_revalidated(self):
        def worker(entered, release):
            with transaction.atomic():
                field = PartnerProgramField.objects.get(pk=self.field.pk)
                field.options = "A|B"
                field.save()
                entered.set()
                if not release.wait(10):
                    raise AssertionError("Lock release timed out")

        def select_removed_option():
            update_program_link_fields(
                self.link.pk, self.user, [{"field_id": self.field.pk, "value_text": "C"}]
            )

        self.run_while_locked(worker, select_removed_option)
        with self.assertRaises(ValidationError):
            select_removed_option()
        self.value.refresh_from_db()
        self.field.refresh_from_db()
        self.assertEqual(self.value.value_text, "B")
        self.assertEqual(self.field.get_options_list(), ["A", "B"])

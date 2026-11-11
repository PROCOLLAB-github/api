"""QA confirmation never consumes other users' mail or sends credentials elsewhere."""

from email.message import EmailMessage
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "deploy/pilot/confirm_qa.py"
spec = importlib.util.spec_from_file_location("pilot_confirm_qa", SOURCE)
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
LEADER = "qa-1794415505972-2b6c7b-leader@example.test"
MEMBER = "qa-1794415505972-2b6c7b-member@example.test"


class PilotQAConfirmation(unittest.TestCase):
    def test_only_accounts_of_one_qa_run_are_allowed(self):
        qa.validate_emails([LEADER, MEMBER])
        for emails in (
            ["admin@example.test"],
            ["user@client.test"],
            [LEADER, LEADER],
            [LEADER, MEMBER.replace("2b6c7b", "ffffff")],
            [],
        ):
            with self.subTest(emails=emails), self.assertRaises(qa.Refused):
                qa.validate_emails(emails)

    def test_reads_multipart_mail_for_exact_recipient(self):
        with TemporaryDirectory() as directory:
            mail = EmailMessage()
            mail["To"] = LEADER
            mail.set_content("Подтверждение регистрации")
            mail.add_alternative(
                '<a href="https://pilot.procollab.ru/program-registration/1'
                '#confirmation=signed%3Aproof">Подтвердить</a>',
                subtype="html",
            )
            (Path(directory) / "email.log").write_bytes(mail.as_bytes())
            self.assertEqual(
                qa.confirmation_from_mail(Path(directory), LEADER), "signed:proof"
            )
            with self.assertRaises(qa.Refused):
                qa.confirmation_from_mail(Path(directory), MEMBER)

    def test_rejects_other_domains_programs_and_receipts(self):
        for link in (
            "https://pilot.procollab.ru.evil.test/program-registration/1#confirmation=x",
            "https://pilot.procollab.ru/program-registration/2#confirmation=x",
            "https://pilot.procollab.ru/program-registration/1#receipt=x",
        ):
            with self.subTest(link=link), TemporaryDirectory() as directory:
                mail = EmailMessage()
                mail["To"] = LEADER
                mail.set_content(link)
                (Path(directory) / "email.log").write_bytes(mail.as_bytes())
                with self.assertRaises(qa.Refused):
                    qa.confirmation_from_mail(Path(directory), LEADER)

    def test_redirect_cannot_send_credentials_outside_pilot(self):
        with self.assertRaises(qa.Refused):
            qa.ScopedRedirect().redirect_request(
                None, None, 302, "", {}, "https://other.test/"
            )


if __name__ == "__main__":
    unittest.main()

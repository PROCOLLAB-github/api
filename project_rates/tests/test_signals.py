from django.test import TestCase

from project_rates.models import Criteria
from project_rates.tests.helpers import create_rate_program


class CriteriaSignalTests(TestCase):
    def test_program_creation_creates_default_comment_criteria(self):
        program = create_rate_program(name="Signal Program")

        self.assertTrue(
            Criteria.objects.filter(
                partner_program=program,
                name="Комментарий",
                type="str",
            ).exists()
        )

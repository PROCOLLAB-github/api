from django.test import TestCase

from industries.tests.helpers import create_industry


class IndustryModelTests(TestCase):
    def test_string_representation_contains_id_and_name(self):
        industry = create_industry(name="Fintech")

        self.assertEqual(str(industry), f"Industry<{industry.id}> - {industry.name}")

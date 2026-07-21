from unittest import TestCase

from procollab.settings_helpers import extend_with_env_list


class ExtendWithEnvListTests(TestCase):
    def test_keeps_base_values_when_env_value_is_empty(self):
        base_values = ["localhost", "procollab.ru"]

        result = extend_with_env_list(base_values, "")

        self.assertEqual(result, base_values)
        self.assertIsNot(result, base_values)

    def test_trims_and_appends_non_empty_values(self):
        result = extend_with_env_list(
            ["localhost"],
            " api-react-dev.procollab.ru, ,react-dev.procollab.ru  ,",
        )

        self.assertEqual(
            result,
            [
                "localhost",
                "api-react-dev.procollab.ru",
                "react-dev.procollab.ru",
            ],
        )

from django.core.cache import cache
from django.test import TestCase

from core.utils import get_users_online_cache_key
from metrics.services import add_total_count, collect_metrics_payload
from metrics.tests.helpers import create_project, create_user, create_vacancy
from users.models import CustomUser


class MetricsServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_collect_metrics_payload_counts_supported_models_and_online_users(self):
        online_user = create_user(
            prefix="metrics-online",
            user_type=CustomUser.ADMIN,
        )
        create_user(prefix="metrics-member")
        create_user(prefix="metrics-mentor", user_type=CustomUser.MENTOR)
        create_user(prefix="metrics-expert", user_type=CustomUser.EXPERT)
        create_user(prefix="metrics-investor", user_type=CustomUser.INVESTOR)
        leader = create_user(
            prefix="metrics-leader",
            user_type=CustomUser.ADMIN,
        )
        project = create_project(leader=leader)
        create_vacancy(project=project)
        cache.set(get_users_online_cache_key(), {online_user.id, leader.id})

        payload = collect_metrics_payload()

        self.assertEqual(payload["total_CustomUser_count"], 6)
        self.assertEqual(payload["total_Member_count"], 1)
        self.assertEqual(payload["total_Mentor_count"], 1)
        self.assertEqual(payload["total_Expert_count"], 1)
        self.assertEqual(payload["total_Investor_count"], 1)
        self.assertEqual(payload["total_Project_count"], 1)
        self.assertEqual(payload["total_Vacancy_count"], 1)
        self.assertEqual(payload["current_online_users"], 2)

    def test_collect_metrics_payload_returns_zero_online_users_for_empty_cache(self):
        payload = collect_metrics_payload()

        self.assertEqual(payload["current_online_users"], 0)

    def test_add_total_count_preserves_existing_payload(self):
        create_user(prefix="metrics-counted")

        payload = add_total_count({"existing": 1}, CustomUser)

        self.assertEqual(payload["existing"], 1)
        self.assertEqual(payload["total_CustomUser_count"], 1)

from django.contrib.auth import get_user_model
from django.core.cache import cache

from core.utils import get_users_online_cache_key
from projects.models import Project
from users.models import Expert, Investor, Member, Mentor
from vacancy.models import Vacancy

User = get_user_model()

METRIC_MODELS = (User, Expert, Investor, Member, Mentor, Project, Vacancy)


def add_total_count(data: dict[str, int], model) -> dict[str, int]:
    new_data = dict(data)
    new_data[f"total_{model.__name__}_count"] = model.objects.count()
    return new_data


def get_current_online_users_count() -> int:
    users_online_list_key = get_users_online_cache_key()
    return len(cache.get_or_set(users_online_list_key, set()))


def collect_metrics_payload() -> dict[str, int]:
    data = {}

    for model in METRIC_MODELS:
        data = add_total_count(data, model)

    data["current_online_users"] = get_current_online_users_count()
    return data

"""Глобальные счётчики legacy-каталога; фильтры выдачи здесь не применяются."""

from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from partner_programs.models import PartnerProgramUserProfile
from projects.models import Collaborator, Project
from users.models import CustomUser


def get_member_statistics():
    """Считает людей одним SQL-запросом, не размножая их по связям.

    EXISTS проверяет участие, а не число проектов/регистраций. Поэтому лидер
    нескольких проектов, который также состоит в команде, учитывается один раз.
    Нижняя граница последних 30 суток включительна и вычисляется один раз.
    """
    since = timezone.now() - timedelta(days=30)
    return (
        CustomUser.objects.filter(user_type=CustomUser.MEMBER, is_active=True)
        .annotate(
            statistics_leader=Exists(
                Project.objects.filter(
                    leader_id=OuterRef("pk"), draft=False, is_public=True
                )
            ),
            statistics_collaborator=Exists(
                Collaborator.objects.filter(
                    user_id=OuterRef("pk"),
                    project__draft=False,
                    project__is_public=True,
                )
            ),
            statistics_program=Exists(
                PartnerProgramUserProfile.objects.filter(
                    user_id=OuterRef("pk"), partner_program__draft=False
                )
            ),
        )
        .aggregate(
            total=Count("pk"),
            in_projects=Count(
                "pk", filter=Q(statistics_leader=True) | Q(statistics_collaborator=True)
            ),
            in_programs=Count("pk", filter=Q(statistics_program=True)),
            new_last_30_days=Count("pk", filter=Q(datetime_created__gte=since)),
        )
    )

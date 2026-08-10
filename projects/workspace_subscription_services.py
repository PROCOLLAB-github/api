from django.db import transaction

from projects.models import Project
from projects.workspace_selectors import (
    filter_workspace_visible_projects,
    get_workspace_subscription_queryset,
)


@transaction.atomic
def set_workspace_project_subscription(
    *, project_id: int, user, is_subscribed: bool
) -> Project:
    """Идемпотентно меняет подписку и возвращает актуальное состояние.

    Сначала проверяем workspace-видимость, затем блокируем только строку Project.
    Все новые mutation endpoints используют одинаковый порядок блокировки, поэтому
    параллельные POST/DELETE не расходятся по count и не блокируют nullable JOIN.
    """
    visible_project_id = (
        filter_workspace_visible_projects(Project.objects.all(), user=user)
        .filter(pk=project_id)
        .values_list("pk", flat=True)
        .first()
    )
    if visible_project_id is None:
        raise Project.DoesNotExist

    project = Project.objects.select_for_update().get(pk=visible_project_id)
    # Видимость проверяется повторно после блокировки: проект мог стать private/draft
    # между первым чтением и началом изменения M2M-связи.
    if not filter_workspace_visible_projects(
        Project.objects.filter(pk=project.pk),
        user=user,
    ).exists():
        raise Project.DoesNotExist

    if is_subscribed:
        project.subscribers.add(user)
    else:
        project.subscribers.remove(user)

    return get_workspace_subscription_queryset(user=user).get(pk=project.pk)

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, Value
from django.db.models.functions import Concat, Lower

from invites.models import Invite
from partner_programs.models import PartnerProgramUserProfile
from projects.models import Collaborator, Project

User = get_user_model()

PROJECT_INVITATION_CANDIDATE_LIMIT = 20


def get_project_invitation_candidates(*, project: Project, query: str):
    """Возвращает безопасный ограниченный queryset кандидатов для Project.

    Selector только помогает лидеру выбрать пользователя. Сервис создания
    приглашения повторно проверяет eligibility, поэтому изменение состава или
    регистрации между поиском и POST не позволяет обойти бизнес-правила.
    """
    collaborators = Collaborator.objects.filter(
        project_id=project.pk,
        user_id=OuterRef("pk"),
    )
    pending_invitations = Invite.objects.filter(
        project_id=project.pk,
        user_id=OuterRef("pk"),
        is_accepted__isnull=True,
        is_revoked=False,
    )

    normalized_query = query.strip()
    # В production PostgreSQL `icontains` регистронезависим для Unicode. Набор
    # вариантов сохраняет такой же результат в локальной SQLite test-среде.
    query_variants = dict.fromkeys(
        (
            normalized_query,
            normalized_query.casefold(),
            normalized_query.lower(),
            normalized_query.upper(),
            normalized_query.title(),
            normalized_query.capitalize(),
        )
    )
    search_filter = Q()
    for query_variant in query_variants:
        search_filter |= (
            Q(first_name__icontains=query_variant)
            | Q(last_name__icontains=query_variant)
            | Q(candidate_full_name__icontains=query_variant)
            | Q(candidate_reverse_name__icontains=query_variant)
            | Q(email__istartswith=query_variant)
        )

    candidates = User.objects.annotate(
        candidate_full_name=Concat("first_name", Value(" "), "last_name"),
        candidate_reverse_name=Concat("last_name", Value(" "), "first_name"),
        candidate_is_collaborator=Exists(collaborators),
        candidate_has_pending_invitation=Exists(pending_invitations),
    ).filter(
        is_active=True,
        candidate_is_collaborator=False,
        candidate_has_pending_invitation=False,
    )

    # Legacy Project считается напрямую связанным максимум с одной программой.
    # Повторяем invariant сервиса создания приглашения, не расширяя его контракт.
    program_id = (
        project.program_links.order_by("pk")
        .values_list("partner_program_id", flat=True)
        .first()
    )
    if program_id is not None:
        program_members = PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_id,
            user_id=OuterRef("pk"),
        )
        candidates = candidates.annotate(
            candidate_is_program_member=Exists(program_members)
        ).filter(candidate_is_program_member=True)

    # Минимальная длина query, DB-limit и project-scoped исключения не дают
    # использовать endpoint как глобальный каталог пользователей платформы.
    return (
        candidates.exclude(pk=project.leader_id)
        .filter(search_filter)
        .only("id", "first_name", "last_name", "avatar")
        .order_by(Lower("last_name"), Lower("first_name"), "pk")[
            :PROJECT_INVITATION_CANDIDATE_LIMIT
        ]
    )

from django.db.models import Exists, OuterRef, Q

from partner_programs.models import PartnerProgram
from partner_programs.permissions import active_programs
from users.models import Expert


ORGANIZER_EVALUATION = Q(draft=False) & ~Q(program_format="noncompetitive")


def program_experts(program_id, *, active_only=True):
    """Expert identities eligible for manual assignment in this program."""
    organizers = PartnerProgram.managers.through.objects.filter(
        partnerprogram_id=program_id, customuser_id=OuterRef("user_id")
    )
    independent = Expert.programs.through.objects.filter(
        partnerprogram_id=program_id, expert_id=OuterRef("pk")
    )
    eligible_program = PartnerProgram.objects.filter(ORGANIZER_EVALUATION, pk=program_id)
    experts = Expert.objects.annotate(is_organizer=Exists(organizers)).filter(
        (Q(is_organizer=True) & Exists(active_programs(eligible_program)))
        | Exists(independent)
    )
    return experts.filter(user__is_active=True) if active_only else experts


def evaluation_programs(user):
    if not user or not user.is_authenticated or not user.is_active:
        return PartnerProgram.objects.none()
    independent = Expert.programs.through.objects.filter(
        partnerprogram_id=OuterRef("pk"), expert__user_id=user.pk
    )
    organizes = PartnerProgram.managers.through.objects.filter(
        partnerprogram_id=OuterRef("pk"), customuser_id=user.pk
    )
    return active_programs(
        PartnerProgram.objects.filter(
            Q(Exists(independent)) | (Q(Exists(organizes)) & ORGANIZER_EVALUATION)
        )
    )


def can_evaluate_program(user, program_id):
    return evaluation_programs(user).filter(pk=program_id).exists()


def has_evaluation_role(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (
            evaluation_programs(user).exists()
            or Expert.objects.filter(user=user).exists()
        )
    )

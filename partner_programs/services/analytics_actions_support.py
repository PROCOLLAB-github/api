"""Shared, read-only helpers for production analytics actions only."""
from django.db.models import Value
from django.db.models.functions import Coalesce, NullIf, Trim
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.permissions import is_program_manager


def managed_program(pk, user, *, lock=False):
    rows = (
        PartnerProgram.objects.select_for_update()
        if lock
        else PartnerProgram.objects.all()
    )
    program = get_object_or_404(rows, pk=pk)
    if not user.is_authenticated or not (
        user.is_staff or user.is_superuser or is_program_manager(user, program)
    ):
        raise PermissionDenied("У вас нет доступа к управлению этой программой.")
    return program


def person_name(user):
    return (
        " ".join(filter(None, (user.first_name, user.last_name, user.patronymic))).strip()
        or "Без имени"
    )


def participant_rows(program):
    return (
        PartnerProgramUserProfile.objects.filter(
            partner_program=program, user__isnull=False
        )
        .select_related("user")
        .annotate(
            participant_region=Coalesce(
                NullIf(Trim("user__city"), Value("")),
                NullIf(Trim("user__region"), Value("")),
                Value(""),
            )
        )
        .order_by("datetime_created", "pk")
    )

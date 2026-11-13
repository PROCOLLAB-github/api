"""Точный поиск почты внутри программы без расширения публичного каталога."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from procollab.white_label import is_white_label_program


@dataclass(frozen=True)
class EmailCandidateScope:
    program_id: int
    email: str


def email_candidate_scope(request):
    if request is None:
        return None
    if hasattr(request, "_white_label_email_candidate_scope"):
        return request._white_label_email_candidate_scope
    request._white_label_email_candidate_scope = None
    user = request.user
    if not user.is_authenticated:
        return None
    email = request.query_params.get("fullname", "").strip()
    try:
        program_id = int(request.query_params.get("partner_program", ""))
        validate_email(email)
    except (ValueError, TypeError, ValidationError):
        return None
    if not is_white_label_program(program_id):
        return None
    allowed = (
        user.is_superuser
        or PartnerProgramUserProfile.objects.filter(
            partner_program_id=program_id, user=user
        ).exists()
        or PartnerProgram.objects.filter(pk=program_id, managers=user).exists()
    )
    if not allowed:
        return None
    scope = EmailCandidateScope(program_id, email)
    request._white_label_email_candidate_scope = scope
    return scope

import re
import unicodedata
from typing import Any

from rest_framework.exceptions import ValidationError


REGISTRATION_CONSENT_KEYS = (
    "personal_data_consent",
    "personalDataConsent",
    "legal_consent",
    "legalConsent",
    "participant_consent",
    "participantConsent",
)

REGISTRATION_REQUIRED_DOCUMENT_TYPES = (
    "privacy_policy",
    "participant_consent",
    "participation_terms",
)

MODERATION_REQUIRED_DOCUMENT_TYPES = (
    "privacy_policy",
    "participant_consent",
    "participation_terms",
    "organizer_terms",
)

SENSITIVE_FIELD_TERMS = (
    "passport",
    "snils",
    "inn",
    "address",
    "bank card",
    "card number",
    "cvv",
    "паспорт",
    "снилс",
    "инн",
    "адрес проживания",
    "банковская карта",
    "номер карты",
)

FIELD_KEYS_TO_SCAN = (
    "label",
    "name",
    "placeholder",
    "helpText",
    "help_text",
    "description",
)


def _normalize_privacy_text(value: Any) -> str:
    text = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", normalized).strip()


NORMALIZED_SENSITIVE_FIELD_TERMS = tuple(
    _normalize_privacy_text(term) for term in SENSITIVE_FIELD_TERMS
)


def iter_data_schema_fields(data_schema: Any) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(data_schema, dict):
        return []

    fields_value = data_schema.get("fields")
    if isinstance(fields_value, list):
        return [
            (str(field.get("id") or field.get("name") or f"field_{index + 1}"), field)
            for index, field in enumerate(fields_value)
            if isinstance(field, dict)
        ]

    return [
        (str(key), value) for key, value in data_schema.items() if isinstance(value, dict)
    ]


def find_forbidden_registration_fields(data_schema: Any) -> list[dict[str, str]]:
    matches = []
    for field_id, field in iter_data_schema_fields(data_schema):
        label = str(field.get("label") or field.get("name") or field_id)
        for source in FIELD_KEYS_TO_SCAN:
            normalized = _normalize_privacy_text(field.get(source))
            if not normalized:
                continue
            for raw_term, normalized_term in zip(
                SENSITIVE_FIELD_TERMS,
                NORMALIZED_SENSITIVE_FIELD_TERMS,
            ):
                if normalized_term and normalized_term in normalized:
                    matches.append(
                        {
                            "field_id": str(field_id),
                            "label": label,
                            "term": raw_term,
                            "source": source,
                        }
                    )
    return matches


def missing_active_legal_document_types(required_types) -> list[str]:
    active_docs = active_legal_documents_by_type()
    return [doc_type for doc_type in required_types if doc_type not in active_docs]


def mask_email(email: str | None) -> str:
    if not email:
        return ""
    local, separator, domain = str(email).partition("@")
    if not separator:
        return "***"
    masked_local = f"{local[:2]}***" if len(local) > 2 else f"{local[:1]}***"
    return f"{masked_local}@{domain}"


def mask_phone(phone: str | int | None) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if not digits:
        return ""
    prefix = "+7" if digits.startswith(("7", "8")) or len(digits) == 10 else "+"
    return f"{prefix} *** ***-**-{digits[-2:]}"


def can_view_participant_contacts(actor, program) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    if getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False):
        return True
    return bool(program.verification_status == "verified" and program.is_manager(actor))


def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}

    forbidden_keys = {
        "email",
        "phone",
        "phone_number",
        "answers",
        "plain_answers",
        "partner_program_data",
    }
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if str(key).casefold() in forbidden_keys:
            continue
        if isinstance(value, dict):
            clean[key] = sanitize_audit_metadata(value)
        elif isinstance(value, list):
            clean[key] = [
                sanitize_audit_metadata(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            clean[key] = value
    return clean


def log_personal_data_access(
    *,
    actor,
    program,
    action: str,
    object_type: str = "",
    object_id: str = "",
    metadata: dict[str, Any] | None = None,
):
    from partner_programs.models import PersonalDataAccessLog

    return PersonalDataAccessLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        program=program,
        action=action,
        object_type=object_type or "",
        object_id=str(object_id or ""),
        metadata=sanitize_audit_metadata(metadata),
    )


def active_legal_documents_by_type() -> dict[str, Any]:
    from partner_programs.models import LegalDocument

    docs = LegalDocument.objects.filter(is_active=True).order_by(
        "type", "-created_at", "-id"
    )
    result = {}
    for doc in docs:
        result.setdefault(doc.type, doc)
    return result


def document_snapshot(document) -> str:
    if not document:
        return ""
    if document.content_html:
        return document.content_html
    return document.content_url or ""


def get_or_create_program_legal_settings(program):
    from partner_programs.models import PartnerProgramLegalSettings

    settings, _ = PartnerProgramLegalSettings.objects.get_or_create(program=program)
    return settings


def program_legal_settings_snapshot(program) -> dict[str, Any]:
    try:
        settings = program.legal_settings
    except Exception:
        settings = None
    if not settings:
        return {}
    return {
        "participation_rules_link": settings.participation_rules_link or "",
        "participation_rules_file": settings.participation_rules_file_id or "",
        "additional_terms_text": settings.additional_terms_text or "",
        "version": settings.terms_version,
    }


def build_participation_terms_snapshot(
    program, active_docs: dict[str, Any]
) -> dict[str, str]:
    settings_snapshot = program_legal_settings_snapshot(program)
    if any(
        settings_snapshot.get(key)
        for key in (
            "participation_rules_link",
            "participation_rules_file",
            "additional_terms_text",
        )
    ):
        return {
            "version": settings_snapshot["version"],
            "snapshot": "\n".join(
                part
                for part in (
                    f"rules_link={settings_snapshot.get('participation_rules_link', '')}",
                    f"rules_file={settings_snapshot.get('participation_rules_file', '')}",
                    settings_snapshot.get("additional_terms_text", ""),
                )
                if part
            ),
        }

    doc = active_docs.get("participation_terms")
    return {
        "version": getattr(doc, "version", ""),
        "snapshot": document_snapshot(doc),
    }


def accept_organizer_terms(*, program, user):
    active_docs = active_legal_documents_by_type()
    organizer_terms = active_docs.get("organizer_terms")
    if not organizer_terms:
        raise ValidationError(
            {
                "detail": "Активный документ с условиями для организатора не найден.",
                "missing_legal_documents": ["organizer_terms"],
            }
        )

    settings = get_or_create_program_legal_settings(program)
    from django.utils import timezone

    settings.organizer_terms_accepted_by = user
    settings.organizer_terms_accepted_at = timezone.now()
    settings.organizer_terms_version = organizer_terms.version
    settings.save(
        update_fields=(
            "organizer_terms_accepted_by",
            "organizer_terms_accepted_at",
            "organizer_terms_version",
            "updated_at",
        )
    )
    return settings


def collect_privacy_blockers(program) -> dict[str, Any]:
    missing_docs = missing_active_legal_document_types(MODERATION_REQUIRED_DOCUMENT_TYPES)
    try:
        legal_settings = program.legal_settings
    except Exception:
        legal_settings = None

    return {
        "missing_legal_documents": missing_docs,
        "organizer_terms_not_accepted": not bool(
            legal_settings and legal_settings.organizer_terms_accepted_at
        ),
        "forbidden_registration_fields": find_forbidden_registration_fields(
            program.data_schema
        ),
    }


def has_privacy_blockers(blockers: dict[str, Any]) -> bool:
    return bool(
        blockers.get("missing_legal_documents")
        or blockers.get("organizer_terms_not_accepted")
        or blockers.get("forbidden_registration_fields")
    )


def request_has_registration_consent(data: dict[str, Any]) -> bool:
    return any(
        data.get(key) is True or data.get(key) == "true"
        for key in REGISTRATION_CONSENT_KEYS
    )


def strip_registration_consent_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in data.items() if key not in REGISTRATION_CONSENT_KEYS
    }


def create_participant_consent(*, program, user, request) -> None:
    from partner_programs.models import PartnerProgramParticipantConsent

    active_docs = active_legal_documents_by_type()
    missing = [
        doc_type
        for doc_type in REGISTRATION_REQUIRED_DOCUMENT_TYPES
        if doc_type not in active_docs
    ]
    if missing:
        raise ValidationError(
            {
                "detail": "Registration is temporarily unavailable: required legal documents are not active.",
                "missing_legal_documents": missing,
            }
        )

    if not request_has_registration_consent(request.data):
        raise ValidationError(
            {
                "personal_data_consent": "Explicit personal data processing consent is required."
            }
        )

    privacy_doc = active_docs["privacy_policy"]
    consent_doc = active_docs["participant_consent"]
    participation_snapshot = build_participation_terms_snapshot(program, active_docs)

    PartnerProgramParticipantConsent.objects.create(
        program=program,
        user=user if getattr(user, "is_authenticated", False) else None,
        consent_document_version=consent_doc.version,
        privacy_policy_version=privacy_doc.version,
        participation_terms_version=participation_snapshot["version"],
        consent_text_snapshot="\n\n".join(
            part
            for part in (
                document_snapshot(consent_doc),
                document_snapshot(privacy_doc),
                participation_snapshot["snapshot"],
            )
            if part
        ),
        ip_address=_request_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
    )


def _request_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or None
    return request.META.get("REMOTE_ADDR", "") or None

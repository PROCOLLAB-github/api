from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from moderation.models import ModerationLog
from moderation.services import get_rejection_reasons
from partner_programs.models import PartnerProgram, PartnerProgramVerificationRequest
from partner_programs.privacy import collect_privacy_blockers
from partner_programs.serializers.verification import (
    PartnerProgramVerificationRequestSerializer,
)
from partner_programs.verification_services import get_verification_rejection_reasons
from project_rates.models import Criteria
from project_rates.serializers import ProgramCriteriaSerializer, ProgramExpertSerializer

MODERATION_REVIEW_DEADLINE = timedelta(days=3)


class ModerationLogSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField(method_name="get_author")
    program = serializers.SerializerMethodField()
    action_label = serializers.CharField(source="get_action_display", read_only=True)
    old_status = serializers.CharField(source="status_before", read_only=True)
    new_status = serializers.CharField(source="status_after", read_only=True)
    reason_code = serializers.CharField(source="rejection_reason", read_only=True)
    rejection_reason_label = serializers.CharField(
        source="get_rejection_reason_display",
        read_only=True,
    )
    reason_label = serializers.CharField(
        source="get_rejection_reason_display",
        read_only=True,
    )
    created_at = serializers.DateTimeField(source="datetime_created", read_only=True)

    class Meta:
        model = ModerationLog
        fields = [
            "id",
            "program",
            "author",
            "actor",
            "action",
            "action_label",
            "status_before",
            "status_after",
            "old_status",
            "new_status",
            "comment",
            "rejection_reason",
            "rejection_reason_label",
            "reason_code",
            "reason_label",
            "sections_to_fix",
            "datetime_created",
            "created_at",
        ]

    def get_author(self, log: ModerationLog) -> dict | None:
        if not log.author:
            return None
        return {
            "id": log.author_id,
            "email": log.author.email,
            "full_name": log.author.get_full_name() or log.author.email,
        }

    def get_program(self, log: ModerationLog) -> dict:
        return {
            "id": log.program_id,
            "name": log.program.name,
            "tag": log.program.tag,
        }


class ModerationProgramListSerializer(serializers.ModelSerializer):
    organizers = serializers.SerializerMethodField()
    managers = serializers.SerializerMethodField(method_name="get_organizers")
    managers_emails = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    submitted_at = serializers.SerializerMethodField()
    decision_at = serializers.SerializerMethodField()
    days_in_moderation = serializers.SerializerMethodField()
    days_frozen = serializers.SerializerMethodField()
    freeze_reason = serializers.SerializerMethodField()
    readiness = serializers.SerializerMethodField()
    readiness_percentage = serializers.SerializerMethodField()
    access_type = serializers.SerializerMethodField()
    registration_type = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    moderation_deadline_at = serializers.SerializerMethodField()
    moderation_overdue_seconds = serializers.SerializerMethodField()
    is_company_verified = serializers.SerializerMethodField()

    class Meta:
        model = PartnerProgram
        fields = [
            "id",
            "name",
            "description",
            "tag",
            "city",
            "image_address",
            "cover_image_address",
            "mobile_cover_image_address",
            "advertisement_image_address",
            "datetime_started",
            "datetime_finished",
            "datetime_registration_ends",
            "datetime_project_submission_ends",
            "datetime_evaluation_ends",
            "status",
            "verification_status",
            "is_private",
            "registration_link",
            "access_type",
            "registration_type",
            "company",
            "is_company_verified",
            "organizers",
            "managers",
            "managers_emails",
            "submitted_at",
            "decision_at",
            "readiness",
            "readiness_percentage",
            "participants_count",
            "moderation_deadline_at",
            "moderation_overdue_seconds",
            "days_in_moderation",
            "days_frozen",
            "freeze_reason",
            "frozen_at",
            "datetime_created",
            "datetime_updated",
        ]

    def get_organizers(self, program: PartnerProgram) -> list[dict]:
        return [_user_summary(manager) for manager in program.managers.all()]

    def get_managers_emails(self, program: PartnerProgram) -> list[str]:
        return [manager.email for manager in program.managers.all()]

    def get_company(self, program: PartnerProgram) -> dict | None:
        return _company_summary(program.company)

    def get_submitted_at(self, program: PartnerProgram):
        annotated = getattr(program, "submitted_at_value", None)
        if annotated is not None:
            return annotated
        fallback = getattr(program, "submitted_at_sort", None)
        if fallback is not None:
            return fallback
        return _get_last_submission_datetime(program)

    def get_decision_at(self, program: PartnerProgram):
        annotated = getattr(program, "decision_at_value", None)
        if annotated is not None:
            return annotated
        return _get_last_decision_datetime(program)

    def get_days_in_moderation(self, program: PartnerProgram) -> int | None:
        submitted_at = self.get_submitted_at(program)
        if submitted_at is None:
            return None
        return (timezone.now() - submitted_at).days

    def get_days_frozen(self, program: PartnerProgram) -> int | None:
        if not program.frozen_at:
            return None
        return (timezone.now() - program.frozen_at).days

    def get_freeze_reason(self, program: PartnerProgram) -> str:
        log = _get_last_freeze_log(program)
        return log.comment if log else ""

    def get_readiness(self, program: PartnerProgram) -> dict:
        return program.calculate_readiness()

    def get_readiness_percentage(self, program: PartnerProgram) -> int:
        return program.get_readiness_percentage()

    def get_access_type(self, program: PartnerProgram) -> str:
        return "closed" if program.is_private else "open"

    def get_registration_type(self, program: PartnerProgram) -> str:
        return "external" if program.registration_link else "internal"

    def get_participants_count(self, program: PartnerProgram) -> int:
        annotated_count = getattr(program, "participants_count_value", None)
        if annotated_count is not None:
            return annotated_count
        return program.users.count()

    def get_moderation_deadline_at(self, program: PartnerProgram):
        submitted_at = self.get_submitted_at(program)
        if submitted_at is None:
            return None
        return submitted_at + MODERATION_REVIEW_DEADLINE

    def get_moderation_overdue_seconds(self, program: PartnerProgram) -> int:
        deadline_at = self.get_moderation_deadline_at(program)
        if deadline_at is None or timezone.now() <= deadline_at:
            return 0
        return int((timezone.now() - deadline_at).total_seconds())

    def get_is_company_verified(self, program: PartnerProgram) -> bool:
        return program.verification_status == PartnerProgram.VERIFICATION_STATUS_VERIFIED


class ModerationProgramDetailSerializer(ModerationProgramListSerializer):
    moderation_history = serializers.SerializerMethodField()
    materials = serializers.SerializerMethodField()
    criteria = serializers.SerializerMethodField()
    experts = serializers.SerializerMethodField()
    operational_readiness_percentage = serializers.SerializerMethodField()
    privacy_warnings = serializers.SerializerMethodField()

    class Meta(ModerationProgramListSerializer.Meta):
        fields = ModerationProgramListSerializer.Meta.fields + [
            "presentation_address",
            "is_competitive",
            "is_distributed_evaluation",
            "max_project_rates",
            "data_schema",
            "projects_availability",
            "publish_projects_after_finish",
            "participation_format",
            "project_team_min_size",
            "project_team_max_size",
            "materials",
            "criteria",
            "experts",
            "operational_readiness_percentage",
            "moderation_history",
            "privacy_warnings",
        ]

    def get_organizers(self, program: PartnerProgram) -> list[dict]:
        managers_data = []
        for manager in program.managers.all():
            managed_programs = manager.managed_partner_programs.all()
            data = _user_summary(manager)
            data.update(
                {
                    "published_programs_count": managed_programs.filter(
                        status=PartnerProgram.STATUS_PUBLISHED
                    ).count(),
                    "completed_programs_count": managed_programs.filter(
                        status=PartnerProgram.STATUS_COMPLETED
                    ).count(),
                }
            )
            managers_data.append(data)
        return managers_data

    def get_moderation_history(self, program: PartnerProgram) -> list[dict]:
        logs = program.moderation_logs.select_related("author", "program").all()
        return ModerationLogSerializer(logs, many=True).data

    def get_materials(self, program: PartnerProgram) -> list[dict]:
        return [_material_summary(material) for material in program.materials.all()]

    def get_criteria(self, program: PartnerProgram) -> list[dict]:
        criteria = Criteria.objects.filter(partner_program=program).order_by("id")
        return ProgramCriteriaSerializer(criteria, many=True).data

    def get_experts(self, program: PartnerProgram) -> list[dict]:
        experts = program.experts.select_related("user").all()
        return ProgramExpertSerializer(
            experts,
            many=True,
            context={"program": program},
        ).data

    def get_operational_readiness_percentage(self, program: PartnerProgram) -> int:
        return program.get_operational_readiness_percentage()

    def get_privacy_warnings(self, program: PartnerProgram) -> dict:
        return collect_privacy_blockers(program)


class ModerationDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=("approve", "reject"))
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    reason_code = serializers.ChoiceField(
        choices=[reason["code"] for reason in get_rejection_reasons()],
        required=False,
        allow_blank=True,
        default="",
    )
    rejection_reason = serializers.ChoiceField(
        choices=[reason["code"] for reason in get_rejection_reasons()],
        required=False,
        allow_blank=True,
        default="",
    )
    sections_to_fix = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        default=list,
    )

    def validate(self, attrs):
        attrs["reason_code"] = attrs.get("reason_code") or attrs.get(
            "rejection_reason",
            "",
        )
        attrs["rejection_reason"] = attrs["reason_code"]
        if attrs["decision"] == "reject":
            if not attrs.get("comment", "").strip():
                raise serializers.ValidationError(
                    {"comment": "Комментарий обязателен при отклонении."}
                )
            if not attrs.get("reason_code"):
                raise serializers.ValidationError(
                    {"reason_code": "Выберите причину отклонения."}
                )
        return attrs


class RejectionReasonSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()


class ModerationVerificationRequestSerializer(
    PartnerProgramVerificationRequestSerializer
):
    requests_history = serializers.SerializerMethodField()

    class Meta(PartnerProgramVerificationRequestSerializer.Meta):
        model = PartnerProgramVerificationRequest
        fields = PartnerProgramVerificationRequestSerializer.Meta.fields + [
            "requests_history",
        ]

    def get_requests_history(self, request_obj):
        history = (
            request_obj.program.verification_requests.select_related(
                "program",
                "company",
                "initiator",
                "decided_by",
            )
            .prefetch_related("documents")
            .order_by("-submitted_at", "-id")
        )
        return PartnerProgramVerificationRequestSerializer(history, many=True).data


class ModerationVerificationDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=("approve", "reject"))
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    reason_code = serializers.ChoiceField(
        choices=[reason["code"] for reason in get_verification_rejection_reasons()],
        required=False,
        allow_blank=True,
        default="",
    )
    rejection_reason = serializers.ChoiceField(
        choices=[reason["code"] for reason in get_verification_rejection_reasons()],
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        attrs["reason_code"] = attrs.get("reason_code") or attrs.get(
            "rejection_reason",
            "",
        )
        attrs["rejection_reason"] = attrs["reason_code"]
        if attrs["decision"] == "reject":
            if not attrs.get("comment", "").strip():
                raise serializers.ValidationError(
                    {"comment": "Комментарий обязателен при отклонении."}
                )
            if get_verification_rejection_reasons() and not attrs.get("reason_code"):
                raise serializers.ValidationError(
                    {"reason_code": "Выберите причину отклонения."}
                )
        return attrs


class ModerationVerificationRevokeSerializer(serializers.Serializer):
    comment = serializers.CharField()

    def validate_comment(self, value):
        if not value.strip():
            raise serializers.ValidationError("Комментарий обязателен при отзыве верификации.")
        return value


def _user_summary(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.get_full_name() or user.email,
        "company": _company_summary(getattr(user, "company", None)),
    }


def _company_summary(company) -> dict | None:
    if not company:
        return None
    return {
        "id": company.id,
        "name": company.name,
        "inn": company.inn,
    }


def _material_summary(material) -> dict:
    file_obj = getattr(material, "file", None)
    return {
        "id": material.id,
        "title": material.title,
        "url": material.url or (file_obj.link if file_obj else ""),
        "type": "file" if file_obj else "link",
        "size": getattr(file_obj, "size", None) if file_obj else None,
        "datetime_created": material.datetime_created,
    }


def _get_last_submission_datetime(program: PartnerProgram):
    log = _get_last_log_by_action(program, ModerationLog.SUBMISSION_ACTIONS)
    return log.datetime_created if log else None


def _get_last_decision_datetime(program: PartnerProgram):
    log = _get_last_log_by_action(program, ModerationLog.DECISION_ACTIONS)
    return log.datetime_created if log else None


def _get_last_freeze_log(program: PartnerProgram):
    return _get_last_log_by_action(
        program,
        (
            ModerationLog.ACTION_AUTO_FREEZE,
            ModerationLog.ACTION_FREEZE,
        ),
    )


def _get_last_log_by_action(program: PartnerProgram, actions):
    prefetched_logs = getattr(program, "_prefetched_objects_cache", {}).get(
        "moderation_logs"
    )
    if prefetched_logs is not None:
        logs = [log for log in prefetched_logs if log.action in actions]
        if not logs:
            return None
        return max(logs, key=lambda log: (log.datetime_created, log.id))

    return (
        program.moderation_logs.filter(action__in=actions)
        .order_by("-datetime_created", "-id")
        .first()
    )

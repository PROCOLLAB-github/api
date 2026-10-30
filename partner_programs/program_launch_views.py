"""Private entry points for the organizer creation flow."""

from rest_framework import serializers
from rest_framework.response import Response

from partner_programs.management_views import ManagementBase
from partner_programs.models import PartnerProgram
from partner_programs.pagination import ProgramAttentionPagination
from partner_programs.permissions import can_create_program, require_create_program
from partner_programs.serializers.management import StrictFieldsMixin
from partner_programs.services import program_launch as service
from partner_programs.services.management import management_data


class CreateProgramInput(StrictFieldsMixin, serializers.Serializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    format = serializers.ChoiceField(choices=service.FORMATS)
    idempotency_key = serializers.UUIDField()


class ManagedProgramsQuery(StrictFieldsMixin, serializers.Serializer):
    search = serializers.CharField(max_length=255, allow_blank=True, default="")
    limit = serializers.IntegerField(min_value=1, max_value=100, default=10)
    offset = serializers.IntegerField(min_value=0, default=0)


class ProgramCapabilitiesView(ManagementBase):
    def get(self, request):
        return Response({"can_create_program": can_create_program(request.user)})


class ProgramDraftCreateView(ManagementBase):
    def post(self, request):
        require_create_program(request.user)
        body = CreateProgramInput(data=request.data)
        body.is_valid(raise_exception=True)
        program, created = service.create_program(request.user, body.validated_data)
        return Response(service.summary(program), status=201 if created else 200)


class ManagedProgramsView(ManagementBase):
    def get(self, request):
        form = ManagedProgramsQuery(data=request.query_params)
        form.is_valid(raise_exception=True)
        rows = PartnerProgram.objects.all()
        if not (request.user.is_staff or request.user.is_superuser):
            rows = rows.filter(managers=request.user)
        if form.validated_data["search"]:
            rows = rows.filter(name__icontains=form.validated_data["search"])
        rows = rows.order_by("-datetime_created", "-pk")
        paginator = ProgramAttentionPagination(form.validated_data)
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response([service.summary(p) for p in page])


class ProgramPreviewView(ManagementBase):
    def get(self, request, pk):
        return Response(service.preview_program(pk, request.user, request))


class ProgramReadinessView(ManagementBase):
    def get(self, request, pk):
        return Response(service.readiness(pk, request.user))


class PublishProgramInput(StrictFieldsMixin, serializers.Serializer):
    revision = serializers.RegexField(r"^[a-f0-9]{64}$", trim_whitespace=False)


class ProgramPublishView(ManagementBase):
    def post(self, request, pk):
        data = PublishProgramInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            service.publish_program(pk, request.user, data.validated_data["revision"])
        )


class ReturnToDraftInput(StrictFieldsMixin, serializers.Serializer):
    expected_updated_at = serializers.DateTimeField()


class ProgramReturnToDraftView(ManagementBase):
    def post(self, request, pk):
        data = ReturnToDraftInput(data=request.data)
        data.is_valid(raise_exception=True)
        program = service.return_to_draft(
            pk, request.user, data.validated_data["expected_updated_at"]
        )
        return Response(management_data(program))

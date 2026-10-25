"""HTTP-контракт C00 для принадлежащих решению приглашений."""

from django.http import Http404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from partner_programs import solution_invitations, solution_team
from partner_programs.solution_api import (
    CommandInteger,
    NameField,
    SolutionAPIView,
    StrictSerializer,
    iso,
    user_data,
)
from partner_programs.solution_errors import MAX_ID
from partner_programs.solution_models import ProgramSolution


class InvitationFields(StrictSerializer):
    role = NameField(
        required=False,
        allow_null=False,
        allow_blank=False,
        min_length=1,
        max_length=128,
        trim_whitespace=False,
    )

    specialization = NameField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=100,
        trim_whitespace=False,
    )
    motivational_letter = NameField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=4096,
        trim_whitespace=False,
    )

    def validate_role(self, value):
        solution_invitations.require_role(value)
        return value


class CreateInvitationSerializer(InvitationFields):
    role = NameField(
        required=True,
        allow_null=False,
        allow_blank=False,
        min_length=1,
        max_length=128,
        trim_whitespace=False,
    )
    expected_solution_version = CommandInteger(min_value=1)
    recipient_user_id = CommandInteger(min_value=1, max_value=MAX_ID)


class UpdateInvitationSerializer(InvitationFields):
    expected_version = CommandInteger(min_value=1)
    expected_solution_version = CommandInteger(min_value=1)

    def validate(self, data):
        if not set(data) & {"role", "specialization", "motivational_letter"}:
            raise ValidationError({"fields": "Укажите изменяемое поле приглашения."})
        return data


class InvitationActionSerializer(StrictSerializer):
    expected_version = CommandInteger(min_value=1)


class InvitationVersionQuery(StrictSerializer):
    expected_version = serializers.RegexField(r"^[1-9][0-9]*$")
    expected_solution_version = serializers.RegexField(r"^[1-9][0-9]*$")


class InvitationListQuery(StrictSerializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)
    status = serializers.ChoiceField(
        choices=["pending", "accepted", "declined"], default="pending"
    )


def invitation_data(invitation, actor):
    solution = invitation.solution
    enabled = solution.program.solution_storage_mode == "solution"
    pending = invitation.status == "pending" and enabled
    mutable = pending and solution.status != "submitted"
    captain, recipient = (
        solution.captain_id == actor.pk,
        invitation.recipient_id == actor.pk,
    )
    name = (
        (solution.submission_snapshot or {}).get("name", solution.name)
        if solution.status == "submitted"
        else solution.name
    )
    return dict(
        id=invitation.pk,
        version=invitation.version,
        program=dict(id=solution.program_id, name=solution.program.name),
        solution=dict(
            kind="solution",
            program_id=solution.program_id,
            solution_id=solution.pk,
            name=name,
        ),
        captain=user_data(solution.captain),
        recipient=user_data(invitation.recipient),
        role=invitation.role,
        specialization=invitation.specialization,
        motivational_letter=invitation.motivational_letter,
        status=invitation.status,
        created_at=iso(invitation.created_at),
        updated_at=iso(invitation.updated_at),
        permissions=dict(
            can_edit=captain and mutable,
            can_revoke=captain and pending,
            can_accept=recipient and mutable,
            can_decline=recipient and pending,
        ),
    )


def invitation_page(query, request):
    serializer = InvitationListQuery(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    rows = query.filter(status=data["status"]).order_by("created_at", "pk")
    offset, limit, total = data["offset"], data["limit"], rows.count()
    stop = offset + limit

    def link(start):
        params = request.query_params.copy()
        params["offset"], params["limit"] = start, limit
        return request.build_absolute_uri("?" + params.urlencode())

    return dict(
        count=total,
        next=link(offset + limit) if offset + limit < total else None,
        previous=link(max(0, offset - limit)) if offset > 0 else None,
        results=[invitation_data(row, request.user) for row in rows[offset:stop]],
    )


def no_query(request):
    serializer = StrictSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)


def read_invitation(invitation_id, actor):
    if not 0 < invitation_id <= MAX_ID:
        raise Http404
    try:
        return solution_invitations.visible_invitations(actor).get(pk=invitation_id)
    except solution_invitations.SolutionInvitation.DoesNotExist:
        raise Http404


class SolutionInvitationsView(SolutionAPIView):
    def get(self, request, pk, solution_id):
        program = solution_team.program_for(pk)
        if not 0 < solution_id <= MAX_ID:
            raise Http404
        try:
            solution = solution_team.visible_solutions(program, request.user).get(
                pk=solution_id
            )
        except ProgramSolution.DoesNotExist:
            raise Http404
        solution_team.require_captain(solution, request.user)
        return Response(
            invitation_page(
                solution_invitations.visible_invitations(request.user).filter(
                    solution=solution
                ),
                request,
            )
        )

    def post(self, request, pk, solution_id):
        no_query(request)
        serializer = CreateInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = solution_invitations.create_invitation(
            program_id=pk,
            solution_id=solution_id,
            actor=request.user,
            **serializer.validated_data
        )
        return Response(
            dict(
                invitation=invitation_data(invitation, request.user),
                solution_version=invitation.solution.version,
            ),
            status=201,
        )


class MySolutionInvitationsView(SolutionAPIView):
    def get(self, request):
        return Response(
            invitation_page(
                solution_invitations.visible_invitations(request.user).filter(
                    recipient=request.user
                ),
                request,
            )
        )


class SolutionInvitationDetailView(SolutionAPIView):
    def get(self, request, invitation_id):
        no_query(request)
        return Response(
            invitation_data(read_invitation(invitation_id, request.user), request.user)
        )

    def patch(self, request, invitation_id):
        no_query(request)
        serializer = UpdateInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = solution_invitations.update_invitation(
            invitation_id=invitation_id, actor=request.user, **serializer.validated_data
        )
        return Response(
            dict(
                invitation=invitation_data(invitation, request.user),
                solution_version=invitation.solution.version,
            )
        )

    def delete(self, request, invitation_id):
        serializer = InvitationVersionQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        if request.data:
            raise ValidationError({"body": "Передайте версии в параметрах запроса."})
        solution_invitations.revoke_invitation(
            invitation_id=invitation_id, actor=request.user, **serializer.validated_data
        )
        return Response(status=204)


class SolutionInvitationActionView(SolutionAPIView):
    decision = None

    def post(self, request, invitation_id):
        no_query(request)
        serializer = InvitationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        accepted = self.decision == "accept"
        invitation = solution_invitations.decide_invitation(
            invitation_id=invitation_id,
            actor=request.user,
            accept=accepted,
            **serializer.validated_data
        )
        data = invitation_data(invitation, request.user)
        return Response(
            dict(
                invitation=data,
                application=data["solution"] if accepted else None,
                solution_version=invitation.solution.version if accepted else None,
            )
        )

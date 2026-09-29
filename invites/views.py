from django_filters import rest_framework as filters
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from invites.filters import InviteFilter
from invites.models import Invite
from invites.permissions import InviteDecisionPermission, InviteDetailPermission
from invites.querysets import get_visible_invites_queryset
from invites.serializers import InviteDetailSerializer, InviteListSerializer
from projects import team_service
from projects.serializers import requested_program_link


class InviteList(generics.ListCreateAPIView):
    serializer_class = InviteDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = InviteFilter

    def get_queryset(self):
        return get_visible_invites_queryset(self.request.user).filter(
            is_accepted__isnull=True
        )

    def create(self, request, *args, **kwargs):
        serializer = InviteListSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(
            InviteDetailSerializer(instance).data,
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(serializer.data),
        )


class InviteDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [InviteDetailPermission]

    def perform_destroy(self, instance):
        team_service.revoke_invite(invite_id=instance.pk, actor=self.request.user)


class InviteAccept(generics.GenericAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [InviteDecisionPermission]

    def post(self, request, *args, **kwargs):
        invite = self.get_object()
        team_service.accept_invite(
            invite_id=invite.pk,
            actor=request.user,
            program_link_id=requested_program_link(request),
        )
        return Response(status=status.HTTP_200_OK)


class InviteDecline(generics.GenericAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [InviteDecisionPermission]

    def post(self, request, *args, **kwargs):
        invite = self.get_object()
        team_service.decline_invite(invite_id=invite.pk, actor=request.user)
        return Response(status=status.HTTP_200_OK)

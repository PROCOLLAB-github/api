from django_filters import rest_framework as filters
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from invites.filters import InviteFilter
from invites.models import Invite
from invites.permissions import InviteDecisionPermission, InviteDetailPermission
from invites.querysets import get_visible_invites_queryset
from invites.serializers import InviteDetailSerializer, InviteListSerializer
from projects.models import Collaborator


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
        serializer = InviteListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["project"].leader != request.user:
            # additional check that the user is the invite's project's leader
            return Response(status=status.HTTP_403_FORBIDDEN)
        instance = serializer.save()
        headers = self.get_success_headers(serializer.data)

        # using detailed serializer so that it'll pass User and Project objects detailed
        detailed_data = InviteDetailSerializer(instance, data=serializer.data)
        detailed_data.is_valid()
        return Response(
            detailed_data.data, status=status.HTTP_201_CREATED, headers=headers
        )


class InviteDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [InviteDetailPermission]


class InviteAccept(generics.GenericAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [InviteDecisionPermission]

    def post(self, request, *args, **kwargs):
        invite = self.get_object()  # type: Invite
        if invite.is_accepted is not None:
            return Response(
                {"detail": "Invite has already been processed."},
                status=status.HTTP_409_CONFLICT,
            )
        # add user to project collaborators
        collaborator, created = Collaborator.objects.get_or_create(
            user=invite.user,
            project=invite.project,
            defaults={
                "role": invite.role,
                "specialization": invite.specialization,
            },
        )
        if not created:
            return Response(
                {"detail": "User is already a collaborator of this project."},
                status=status.HTTP_409_CONFLICT,
            )
        invite.is_accepted = True
        invite.save()
        return Response(status=status.HTTP_200_OK)


class InviteDecline(generics.GenericAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [InviteDecisionPermission]

    def post(self, request, *args, **kwargs):
        invite = self.get_object()
        if invite.is_accepted is not None:
            return Response(
                {"detail": "Invite has already been processed."},
                status=status.HTTP_409_CONFLICT,
            )
        invite.is_accepted = False
        invite.save()
        return Response(status=status.HTTP_200_OK)

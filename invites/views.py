from django_filters import rest_framework as filters
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from invites.filters import InviteFilter
from invites.models import Invite
from invites.serializers import InviteListSerializer, InviteDetailSerializer


class InviteList(generics.ListCreateAPIView):
    queryset = Invite.objects.get_invite_for_list_view()
    serializer_class = InviteDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = InviteFilter

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
    queryset = Invite.objects.all()
    serializer_class = InviteDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class InviteAccept(generics.GenericAPIView):
    queryset = Invite.objects.all()
    serializer_class = InviteDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def post(self, request, *args, **kwargs):
        invite = self.get_object()
        if invite.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        # add user to project collaborators
        invite.project.collaborators.add(invite.user)
        invite.is_accepted = True
        invite.save()
        return Response(status=status.HTTP_200_OK)


class InviteDecline(generics.GenericAPIView):
    queryset = Invite.objects.all()
    serializer_class = InviteDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def post(self, request, *args, **kwargs):
        invite = self.get_object()
        if invite.user != request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        invite.is_accepted = False
        invite.save()
        return Response(status=status.HTTP_200_OK)

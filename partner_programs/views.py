from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from partner_programs.models import PartnerProgram
from partner_programs.serializers import (
    PartnerProgramListSerializer,
    PartnerProgramDetailSerializer,
    PartnerProgramUserSerializer,
    PartnerProgramNewUserSerializer,
)


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class PartnerProgramDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class PartnerProgramCreateUserAndRegister(generics.GenericAPIView):
    """
    Create new user and register him to program and save additional data
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramNewUserSerializer

    def post(self, request, *args, **kwargs):
        # program = PartnerProgram.objects.get(pk=kwargs["pk"])
        # todo
        # register new user
        # create PartnerProgram m2m table if not created
        # add user to m2m
        return Response(status=status.HTTP_201_CREATED)


class PartnerProgramRegister(generics.GenericAPIView):
    """
    Register user to program and save additional data
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramUserSerializer

    def post(self, request, *args, **kwargs):
        # todo
        return Response(status=status.HTTP_201_CREATED)

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.serializers import (
    PartnerProgramDetailSerializer,
    PartnerProgramListSerializer,
    PartnerProgramNewUserSerializer,
    PartnerProgramUserSerializer,
)

User = get_user_model()


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PartnerProgramPagination

    def get(self, request, *args, **kwargs):
        programs = self.paginate_queryset(self.get_queryset())
        context = {"user": request.user}
        serializer = PartnerProgramListSerializer(programs, context=context, many=True)
        return self.get_paginated_response(serializer.data)


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
        # register new user
        # create PartnerProgram m2m table if not created
        # add user to m2m
        # program = PartnerProgram.objects.get(pk=kwargs["pk"])
        # user = User()
        # print(request.data)
        return Response(status=status.HTTP_201_CREATED)


class PartnerProgramRegister(generics.GenericAPIView):
    """
    Register user to program and save additional program data
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramUserSerializer

    def post(self, request, *args, **kwargs):
        try:
            program = PartnerProgram.objects.get(pk=kwargs["pk"])
            user_to_add = request.user
            user_profile_program_data = request.data

            added_user_profile = PartnerProgramUserProfile(
                partner_program_data=user_profile_program_data,
                user=user_to_add,
                partner_program=program,
            )
            added_user_profile.save()

            return Response(status=status.HTTP_201_CREATED)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except IntegrityError:
            return Response(
                data={"detail": "User already registered to this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )

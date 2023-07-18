from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.serializers import SetLikedSerializer
from core.services import set_like, add_view
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.serializers import (
    PartnerProgramListSerializer,
    PartnerProgramNewUserSerializer,
    PartnerProgramUserSerializer,
    PartnerProgramDataSchemaSerializer,
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
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


class PartnerProgramDetail(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get(self, request, *args, **kwargs):
        try:
            program = PartnerProgram.objects.get(pk=kwargs["pk"])
            is_user_member = program.users.filter(pk=request.user.pk).exists()
            if is_user_member:
                serializer_class = PartnerProgramForMemberSerializer
            else:
                serializer_class = PartnerProgramForUnregisteredUserSerializer
            data = serializer_class(program).data
            data["is_user_member"] = is_user_member
            return Response(data=data, status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramCreateUserAndRegister(generics.GenericAPIView):
    """
    Create new user and register him to program and save additional data
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramNewUserSerializer

    def post(self, request, *args, **kwargs):
        try:
            program = PartnerProgram.objects.get(pk=kwargs["pk"])
            data = request.data
            user_fields = (
                "email",
                "password",
                "first_name",
                "last_name",
                "patronymic",
                "birthday",
                "city",
            )
            # fixme: should we set verification_date?, if no then we need to ad them to ClickUp list
            user = User(
                **{field_name: data[field_name] for field_name in user_fields},
                is_active=True,  # bypass email verification
                onboarding_stage=None,  # bypass onboarding
            )
            user.save()

            user_profile_program_data = {
                field_name: data.get(field_name)
                for field_name in data
                if field_name not in user_fields
            }
            added_user_profile = PartnerProgramUserProfile(
                partner_program_data=user_profile_program_data,
                user=user,
                partner_program=program,
            )
            added_user_profile.save()
            return Response(status=status.HTTP_201_CREATED)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


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


class PartnerProgramSetViewed(generics.GenericAPIView):
    # fixme
    # serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = PartnerProgram.objects.get(pk=self.kwargs["pk"])
            add_view(program, request.user)
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramSetLiked(generics.CreateAPIView):
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = PartnerProgram.objects.get(pk=self.kwargs["pk"])
            set_like(program, request.user, request.data.get("is_liked"))
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramDataSchema(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramDataSchemaSerializer
    permission_classes = [permissions.IsAuthenticated]

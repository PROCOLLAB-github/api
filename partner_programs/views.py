from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.serializers import SetLikedSerializer, SetViewedSerializer
from core.services import add_view, set_like
from partner_programs.helpers import date_to_iso
from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
from partner_programs.pagination import PartnerProgramPagination
from partner_programs.serializers import (
    PartnerProgramDataSchemaSerializer,
    PartnerProgramForMemberSerializer,
    PartnerProgramForUnregisteredUserSerializer,
    PartnerProgramListSerializer,
    PartnerProgramNewUserSerializer,
    PartnerProgramUserSerializer,
)

User = get_user_model()


class PartnerProgramList(generics.ListCreateAPIView):
    queryset = PartnerProgram.objects.filter(draft=False)
    serializer_class = PartnerProgramListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = PartnerProgramPagination


class PartnerProgramDetail(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    serializer_class = PartnerProgramForUnregisteredUserSerializer

    def get(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            is_user_member = program.users.filter(pk=request.user.pk).exists()
            serializer_class = (
                PartnerProgramForMemberSerializer
                if is_user_member
                else PartnerProgramForUnregisteredUserSerializer
            )
            data = serializer_class(program).data
            data["is_user_member"] = is_user_member
            if request.user.is_authenticated:
                add_view(program, request.user)

            return Response(data=data, status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramCreateUserAndRegister(generics.GenericAPIView):
    """
    Create new user and register him to program and save additional data.
    If a user with such an email already exists in the system, then his profile
    remains the same, but he registers in the program with the specified data.
    """

    permission_classes = [AllowAny]
    serializer_class = PartnerProgramNewUserSerializer
    queryset = PartnerProgram.objects.all()

    def post(self, request, *args, **kwargs):
        data = request.data
        # tilda cringe
        if data.get("test") == "test":
            return Response(status=status.HTTP_200_OK)

        try:
            program = self.get_object()
        except PartnerProgram.DoesNotExist:
            return Response({"asd": "asd"}, status=status.HTTP_404_NOT_FOUND)

        # tilda cringe
        email = data.get("email") if data.get("email") else data.get("email_")
        if not email:
            return Response(
                data={"detail": "You need to pass an email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        password = data.get("password")
        if not password:
            return Response(
                data={"detail": "You need to pass a password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_fields = (
            "first_name",
            "last_name",
            "patronymic",
            "city",
        )
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "birthday": date_to_iso(data.get("birthday", "01-01-1900")),
                "is_active": True,  # bypass email verification
                "onboarding_stage": None,  # bypass onboarding
                "verification_date": timezone.now(),  # bypass ClickUp verification
                **{field_name: data.get(field_name, "") for field_name in user_fields},
            }
        )
        if created:  # Only when registering a new user.
            user.set_password(password)
            user.save()

        user_profile_program_data = {
            k: v for k, v in data.items() if k not in user_fields and k != "password"
        }
        try:
            PartnerProgramUserProfile.objects.create(
                partner_program_data=user_profile_program_data,
                user=user,
                partner_program=program,
            )
        except IntegrityError:
            return Response(
                data={"detail": "User has already registered in this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_201_CREATED)

    def get(self, request, *args, **kwargs):
        return Response(status=status.HTTP_200_OK)


class PartnerProgramRegister(generics.GenericAPIView):
    """
    Register user to program and save additional program data
    """

    queryset = PartnerProgram.objects.none()
    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramUserSerializer

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            if program.datetime_registration_ends < timezone.now():
                return Response(
                    data={"detail": "Registration period has ended."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
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
    queryset = PartnerProgram.objects.none()
    serializer_class = SetViewedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            add_view(program, request.user)
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramSetLiked(generics.CreateAPIView):
    queryset = PartnerProgram.objects.none()
    serializer_class = SetLikedSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            program = self.get_object()
            set_like(program, request.user, request.data.get("is_liked"))
            return Response(status=status.HTTP_200_OK)
        except PartnerProgram.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class PartnerProgramDataSchema(generics.RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    serializer_class = PartnerProgramDataSchemaSerializer
    permission_classes = [permissions.IsAuthenticated]

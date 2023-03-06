from datetime import datetime

import jwt
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django_filters import rest_framework as filters
from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    UpdateAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from core.permissions import IsOwnerOrReadOnly
from core.utils import Email
from projects.serializers import ProjectListSerializer
from users.helpers import VERBOSE_ROLE_TYPES, VERBOSE_USER_TYPES
from users.models import UserAchievement, LikesOnProject
from users.permissions import IsAchievementOwnerOrReadOnly
from users.serializers import (
    AchievementDetailSerializer,
    AchievementListSerializer,
    EmailSerializer,
    PasswordSerializer,
    UserDetailSerializer,
    UserListSerializer,
    VerifyEmailSerializer,
)
from .filters import UserFilter

User = get_user_model()
Project = apps.get_model("projects", "Project")


class UserList(ListCreateAPIView):
    queryset = User.objects.get_active()
    permission_classes = [AllowAny]
    serializer_class = UserListSerializer
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = UserFilter

    def get(self, request, *args, **kwargs):
        if request.user and request.user.is_authenticated:
            return super().get(request, *args, **kwargs)
        return Response(
            {
                "error": "you must be authenticated for this"
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        user = User.objects.get(email=serializer.data["email"])

        token = RefreshToken.for_user(user).access_token

        relative_link = reverse("users:account_email_verification_sent")
        current_site = get_current_site(request).domain
        absolute_url = "http://" + current_site + relative_link + "?token=" + str(token)

        email_body = "Hi, {} {}! Use link below verify your email {}".format(
            user.first_name, user.last_name, absolute_url
        )

        data = {
            "email_body": email_body,
            "email_subject": "Verify your email",
            "to_email": user.email,
        }

        Email.send_email(data)

        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class LikedProjectList(ListAPIView):
    serializer_class = ProjectListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        projects_ids_list = LikesOnProject.objects.filter(
            user=self.request.user, is_liked=True
        ).values_list("project", flat=True)

        return Project.objects.get_projects_from_list_of_ids(projects_ids_list)


class UserAdditionalRolesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Return a tuple of user additional roles types.
        """
        return Response(VERBOSE_ROLE_TYPES, status=status.HTTP_200_OK)


class SpecialistsList(ListAPIView):
    """
    This view returns a list of specialists: investors, experts and mentors.
    """

    queryset = User.objects.filter(
        Q(user_type=User.EXPERT) | Q(user_type=User.MENTOR) | Q(user_type=User.INVESTOR)
    )
    permission_classes = [IsAuthenticated]
    serializer_class = UserListSerializer


class UserDetail(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.get_users_for_detail_view()
    permission_classes = [IsOwnerOrReadOnly, IsAuthenticated]
    serializer_class = UserDetailSerializer

    @transaction.atomic
    def put(self, request, pk):
        # bootleg version of updating achievements via user
        if request.data.get("achievements") is not None:
            achievements = request.data.get("achievements")
            # delete all old achievements
            UserAchievement.objects.filter(user_id=pk).delete()
            # create new achievements
            UserAchievement.objects.bulk_create(
                [
                    UserAchievement(
                        user_id=pk,
                        title=achievement.get("title"),
                        status=achievement.get("status"),
                    )
                    for achievement in achievements
                ]
            )
        return super().put(request, pk)

    @transaction.atomic
    def patch(self, request, pk):
        return super().patch(request, pk)


class CurrentUser(GenericAPIView):
    queryset = User.objects.get_users_for_detail_view()
    permission_classes = [IsAuthenticated]
    serializer_class = UserDetailSerializer

    def get(self, request):
        user = request.user
        serializer = self.get_serializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserTypesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Return a list of tuples [(id, name), ..] of user types.
        """
        return Response(VERBOSE_USER_TYPES)


class VerifyEmail(GenericAPIView):
    serializer_class = VerifyEmailSerializer
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.GET.get("token")
        REDIRECT_URL = "https://app.procollab.ru/auth/verification/"
        try:
            payload = jwt.decode(jwt=token, key=settings.SECRET_KEY, algorithms=["HS256"])
            user = User.objects.get(id=payload["user_id"])
            access_token = RefreshToken.for_user(user).access_token
            refresh_token = RefreshToken.for_user(user)

            if not user.is_active:
                user.is_active = True
                user.save()

            return redirect(
                f"{REDIRECT_URL}?access_token={access_token}&refresh_token={refresh_token}",
                status=status.HTTP_200_OK,
                message="Succeed",
            )

        except jwt.ExpiredSignatureError:
            return redirect(
                REDIRECT_URL,
                status=status.HTTP_400_BAD_REQUEST,
                message="Activate Expired",
            )
        except jwt.DecodeError:
            return redirect(
                REDIRECT_URL,
                status=status.HTTP_400_BAD_REQUEST,
                message="Decode error",
            )


class EmailResetPassword(GenericAPIView):
    serializer_class = EmailSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid()

        user = User.objects.get(email=serializer.data["email"])

        access_token = RefreshToken.for_user(user).access_token
        refresh_token = RefreshToken.for_user(user)

        relative_link = reverse("users:password_reset_sent")

        current_site = get_current_site(request).domain
        absolute_url = (
                "http://"
                + current_site
                + relative_link
                + f"?access_token={access_token}&refresh_token={refresh_token}"
        )

        email_body = "Hi, {} {}! Use link below for reset password {}".format(
            user.first_name, user.last_name, absolute_url
        )

        data = {
            "email_body": email_body,
            "email_subject": "Reset password",
            "to_email": user.email,
        }

        Email.send_email(data)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ResetPassword(UpdateAPIView):
    serializer_class = PasswordSerializer
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        refresh_token = request.GET.get("refresh_token")
        try:
            RefreshToken(refresh_token).check_blacklist()
        except TokenError:
            return redirect(
                "https://procollab.ru/auth/reset_password/",
                status=status.HTTP_400_BAD_REQUEST,
                message="Used token",
            )

        return Response({"message": "Enter new password"})

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid()

        try:
            refresh_token = request.GET.get("refresh_token")
            access_token = request.GET.get("access_token")
            payload = jwt.decode(
                jwt=access_token, key=settings.SECRET_KEY, algorithms=["HS256"]
            )
            user = User.objects.get(id=payload["user_id"])
            last_update = user.datetime_updated
            frequency_update = datetime.utcnow().minute - last_update.minute
            if frequency_update <= 10:
                return redirect(
                    "https://procollab.ru/auth/reset_password/",
                    status=status.HTTP_400_BAD_REQUEST,
                    message="You can't change your password so often",
                )

            user.set_password(serializer.data["new_password"])
            user.save()

            RefreshToken(refresh_token).blacklist()
            return redirect(
                "https://procollab.ru/auth/reset_password/",
                status=status.HTTP_200_OK,
                message="Succeed",
            )

        except jwt.ExpiredSignatureError:
            return redirect(
                "https://procollab.ru/auth/reset_password/",
                status=status.HTTP_400_BAD_REQUEST,
                message="Activate Expired",
            )
        except jwt.DecodeError:
            return redirect(
                "https://procollab.ru/auth/reset_password/",
                status=status.HTTP_400_BAD_REQUEST,
                message="Decode error",
            )


class AchievementList(ListCreateAPIView):
    queryset = UserAchievement.objects.get_achievements_for_list_view()
    serializer_class = AchievementListSerializer
    permission_classes = [IsAchievementOwnerOrReadOnly]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.validated_data["user"] = request.user
        # warning for someone who tries to set user variable (the user will always be yourself anyway)
        if (
                request.data.get("user") is not None
                and request.data.get("user") != request.user.id
        ):
            return Response(
                {
                    "error": "you can't edit USER field for this view since "
                             "you can't create achievements for other people"
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class AchievementDetail(RetrieveUpdateDestroyAPIView):
    queryset = UserAchievement.objects.get_achievements_for_detail_view()
    serializer_class = AchievementDetailSerializer
    permission_classes = [IsAchievementOwnerOrReadOnly]


class UserProjectsList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = ProjectListSerializer(
            Project.objects.get_user_projects_for_list_view().filter(
                Q(leader_id=self.request.user.id)
                | Q(collaborator__user=self.request.user)
            ),
            many=True,
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # get refresh token from request body
            try:
                refresh_token = request.data["refresh_token"]
            except KeyError:
                return Response(
                    {"error": "Provide refresh_token in data"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # blacklist the refresh token
            RefreshToken(refresh_token).blacklist()
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except TokenError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

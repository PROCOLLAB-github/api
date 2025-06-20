import urllib.parse

import jwt
import requests
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_yasg.utils import swagger_auto_schema
from rest_framework import exceptions, permissions, status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from weasyprint import HTML

from core.models import SkillToObject, Specialization, SpecializationCategory
from core.pagination import Pagination
from core.permissions import IsOwnerOrReadOnly
from events.models import Event
from events.serializers import EventsListSerializer
from partner_programs.models import PartnerProgram
from partner_programs.serializers import (
    PartnerProgramListSerializer,
    UserProgramsSerializer,
)
from projects.pagination import ProjectsPagination
from projects.serializers import ProjectListSerializer
from users.constants import (
    VERBOSE_ROLE_TYPES,
    VERBOSE_USER_TYPES,
    VERIFY_EMAIL_REDIRECT_URL,
    OnboardingStage,
)
from users.helpers import (
    check_related_fields_update,
    force_verify_user,
    verify_email,
)
from users.models import LikesOnProject, UserAchievement, UserSkillConfirmation
from users.permissions import IsAchievementOwnerOrReadOnly
from users.serializers import (
    AchievementDetailSerializer,
    AchievementListSerializer,
    PublicUserSerializer,
    RemoteBuySubSerializer,
    ResendVerifyEmailSerializer,
    SpecializationSerializer,
    SpecializationsSerializer,
    UserApproveSkillResponse,
    UserCloneDataSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserProjectListSerializer,
    UserSkillConfirmationSerializer,
    UserSubscribedProjectsSerializer,
    UserSubscriptionDataSerializer,
    VerifyEmailSerializer,
)
from users.typing import UserCVDataV2

from .filters import SpecializationFilter, UserFilter
from .helpers import check_chache_for_cv
from .pagination import UsersPagination
from .schema import SKILL_PK_PARAM, USER_PK_PARAM
from .services.cv_data_prepare import UserCVDataPreparerV2
from .services.verification import VerificationTasks
from .tasks import send_mail_cv

User = get_user_model()
Project = apps.get_model("projects", "Project")


class UserList(ListCreateAPIView):
    queryset = User.objects.get_active()
    serializer_class = UserListSerializer
    pagination_class = UsersPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = UserFilter

    def get_permissions(self):
        if self.request.method == "POST":
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAdminUser]
        return [permission() for permission in permission_classes]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        user = User.objects.get(email=serializer.data["email"])

        verify_email(user, request)

        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


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
        check_related_fields_update(request.data, pk)
        return super().put(request, pk)

    @transaction.atomic
    def patch(self, request, pk):
        check_related_fields_update(request.data, pk)
        return super().patch(request, pk)


class CurrentUserProgramsTags(RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = UserProgramsSerializer

    def get(self, request, *args, **kwargs):
        user = User.objects.get(id=request.user.id)
        # fixme: mb hide finished programs
        programs = [
            profile.partner_program for profile in user.partner_program_profiles.all()
        ]
        serializer = self.get_serializer(programs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class CurrentUserPrograms(RetrieveAPIView):
    queryset = PartnerProgram.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = PartnerProgramListSerializer

    def get(self, request, *args, **kwargs):
        user = User.objects.get(id=request.user.id)
        # fixme: mb hide finished programs
        programs = [
            profile.partner_program for profile in user.partner_program_profiles.all()
        ]
        serializer = self.get_serializer(programs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserSkillsApproveDeclineView(APIView):
    queryset = UserSkillConfirmation.objects.all()
    permission_classes = [IsAuthenticated]
    serializer_class = UserSkillConfirmationSerializer

    @swagger_auto_schema(
        request_body=None,
        operation_description=(
            "Create skill confirmation.\nData in the body not required, "
            "it is enough to pass the parameters `user_pk` == `user.id` "
            "and `skill_pk` == `skill.id` in the query string."
        ),
        manual_parameters=[USER_PK_PARAM, SKILL_PK_PARAM],
        responses={201: UserApproveSkillResponse},
    )
    def post(self, request, *args, **kwargs) -> Response:
        """Create confirmation of user skill by current user."""
        skill_to_object: SkillToObject = self._get_skill_to_object()
        data: dict[str, int] = {
            "skill_to_object": skill_to_object.id,
            "confirmed_by": request.user.id,
        }
        serializer = self.serializer_class(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(
        operation_description=(
            "Delete skill confirmation. `user_pk` == `user.id` "
            "`skill_pk` == `skill.id` in the query string."
        ),
        manual_parameters=[USER_PK_PARAM, SKILL_PK_PARAM],
    )
    def delete(self, request, *args, **kwargs) -> Response:
        """Delete confirmation of user skill by current user."""
        instance: UserSkillConfirmation = self.get_object()
        if instance.confirmed_by != request.user:
            return Response(
                {"error": "You can only delete your own confirmations."},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_object(self) -> UserSkillConfirmation:
        skill_confirmation_object = get_object_or_404(
            self.queryset,
            skill_to_object=self._get_skill_to_object(),
            confirmed_by=self.request.user.pk,
        )
        return skill_confirmation_object

    def _get_skill_to_object(self) -> SkillToObject:
        """Returns the `SkillToObject` instance of the user whose skill needs to be confirmed."""
        content_type = ContentType.objects.get_for_model(User)
        skill_to_object = get_object_or_404(
            SkillToObject,
            object_id=self.kwargs["user_pk"],
            content_type=content_type,
            skill_id=self.kwargs["skill_pk"],
        )
        return skill_to_object


class CurrentUser(GenericAPIView):
    queryset = User.objects.get_users_for_detail_view()
    permission_classes = [IsAuthenticated]
    serializer_class = UserDetailSerializer

    def get(self, request):
        user = request.user
        serializer = self.get_serializer(user)

        if settings.DEBUG:
            skills_url_name = (
                "https://skills.dev.procollab.ru/progress/subscription-data/"
            )
        else:
            skills_url_name = (
                "https://api.skills.procollab.ru/progress/subscription-data/"
            )
        try:
            subscription_data = requests.get(
                skills_url_name,
                headers={
                    "accept": "application/json",
                    "Authorization": request.META.get("HTTP_AUTHORIZATION"),
                },
            )
            subscription_serializer = UserSubscriptionDataSerializer(
                subscription_data.json()
            )
            subs_data = subscription_serializer.data
        except Exception:
            subs_data = {}

        return Response(serializer.data | subs_data, status=status.HTTP_200_OK)


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

        try:
            payload = jwt.decode(
                jwt=token, key=settings.SECRET_KEY, algorithms=["HS256"]
            )
            user = User.objects.get(id=payload["user_id"])
            access_token = RefreshToken.for_user(user).access_token
            refresh_token = RefreshToken.for_user(user)

            if not user.is_active:
                user.is_active = True
                user.save()

            return redirect(
                f"{VERIFY_EMAIL_REDIRECT_URL}?access_token={access_token}&refresh_token={refresh_token}",
                status=status.HTTP_200_OK,
                message="Succeed",
            )

        except jwt.ExpiredSignatureError:
            return redirect(
                VERIFY_EMAIL_REDIRECT_URL,
                status=status.HTTP_400_BAD_REQUEST,
                message="Activate Expired",
            )
        except jwt.DecodeError:
            return redirect(
                VERIFY_EMAIL_REDIRECT_URL,
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
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )


class AchievementDetail(RetrieveUpdateDestroyAPIView):
    queryset = UserAchievement.objects.get_achievements_for_detail_view()
    serializer_class = AchievementDetailSerializer
    permission_classes = [IsAchievementOwnerOrReadOnly]


class UserProjectsList(GenericAPIView):
    permission_classes = [IsAuthenticated]
    pagination_class = ProjectsPagination
    serializer_class = UserProjectListSerializer

    def get(self, request):
        self.queryset = Project.objects.get_user_projects_for_list_view().filter(
            Q(leader_id=self.request.user.id) | Q(collaborator__user=self.request.user)
        )

        page = self.paginate_queryset(self.queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(
            {"detail": "Unable to return paginated list"},
            status=status.HTTP_400_BAD_REQUEST,
        )


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


class RegisteredEventsList(ListAPIView):
    serializer_class = EventsListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        events = Event.objects.filter(registered_users__pk=self.request.user.pk)
        return events


class SetUserOnboardingStage(APIView):
    def put(self, request: Request, pk):
        try:
            if request.user.pk != pk:
                return Response(
                    status=status.HTTP_403_FORBIDDEN,
                    data={"error": "You cannot edit other users!"},
                )

            new_stage = request.data["onboarding_stage"]

            if new_stage not in [None, *range(3)]:
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"error": "Wrong onboarding stage number!"},
                )
            # if the user was on the last stage and passed it
            if (
                request.user.onboarding_stage == OnboardingStage.account_type.value
                and new_stage == OnboardingStage.completed.value
            ):
                VerificationTasks.create(request.user)

            request.user.onboarding_stage = new_stage
            request.user.save()

            serialized_user = UserListSerializer(
                request.user, context={"request": request}
            )
            data = serialized_user.data
            return Response(status=status.HTTP_200_OK, data=data)
        except Exception:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"error": "Something went wrong"},
            )


class ResendVerifyEmail(GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ResendVerifyEmailSerializer

    def post(self, request, *args, **kwargs):
        try:
            email = request.data["email"]
            user = User.objects.get(email=email)

            if not user.is_active:
                verify_email(user, request)
                return Response("Email sent!", status=status.HTTP_200_OK)

            return Response("User already verified!", status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(
                "User with given email does not exists!",
                status=status.HTTP_404_NOT_FOUND,
            )


class ForceVerifyView(APIView):
    queryset = User.objects.get_users_for_detail_view()
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, *args, **kwargs):
        try:
            user = User.objects.get(pk=kwargs["pk"])
            force_verify_user(user)
            return Response(status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)


class UserSubscribedProjectsList(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSubscribedProjectsSerializer
    pagination_class = Pagination

    def get_queryset(self):
        try:
            user = User.objects.get(pk=self.kwargs["pk"])
            return user.subscribed_projects.all()
        except User.DoesNotExist:
            raise exceptions.NotFound


class UserSpecializationsNestedView(GenericAPIView):
    serializer_class = SpecializationsSerializer
    queryset = SpecializationCategory.objects.all()

    def get(self, request):
        data = self.serializer_class(self.get_queryset(), many=True).data
        return Response(status=status.HTTP_200_OK, data=data)


class UserSpecializationsInlineView(ListAPIView):
    serializer_class = SpecializationSerializer
    pagination_class = Pagination
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = SpecializationFilter

    def get_queryset(self):
        return Specialization.objects.all()


class SingleUserDataView(ListAPIView):
    serializer_class = UserCloneDataSerializer
    permissions = [AllowAny]
    authentication_off = True

    def get_queryset(self) -> User:
        return [get_object_or_404(User, email=self.request.data["email"])]


class RemoteViewSubscriptions(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        try:
            subscriptions = self._get_response_from_remote_api()
            return Response(subscriptions, status=status.HTTP_200_OK)
        except requests.RequestException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _get_link_to_remote_api(self) -> str:
        # TODO something to reuse this code
        if settings.DEBUG:
            subscriptions_url = "https://skills.dev.procollab.ru/subscription/"
        else:
            subscriptions_url = "https://api.skills.procollab.ru/subscription/"
        return subscriptions_url

    def _get_response_from_remote_api(self):
        subscriptions_url = self._get_link_to_remote_api()
        response = requests.get(
            subscriptions_url,
            headers={
                "accept": "application/json",
                "Authorization": self.request.META.get("HTTP_AUTHORIZATION"),
            },
        )
        response.raise_for_status()
        return response.json()


class RemoteCreatePayment(GenericAPIView):
    serializer_class = RemoteBuySubSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            subscriptions_buy_url = self._get_link_to_remote_api()
            data, headers = self._get_data_to_request_remote_api()
            response = requests.post(subscriptions_buy_url, json=data, headers=headers)
            response.raise_for_status()
            return Response(response.json(), status=status.HTTP_200_OK)
        except requests.RequestException as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def _get_link_to_remote_api(self) -> str:
        # TODO something to reuse this code
        if settings.DEBUG:
            subscriptions_buy_url = "https://skills.dev.procollab.ru/subscription/buy/"
        else:
            subscriptions_buy_url = "https://api.skills.procollab.ru/subscription/buy/"
        return subscriptions_buy_url

    def _get_data_to_request_remote_api(self) -> tuple[dict, dict]:
        serializer = self.serializer_class(data=self.request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            headers = {
                "accept": "application/json",
                "Authorization": self.request.META.get("HTTP_AUTHORIZATION"),
            }
            return data, headers

        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserCVDownload(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs) -> HttpResponse:
        user_id: int = request.user.id
        cache_key: str = f"user_cv_download_mail_{user_id}"
        cooldown_time: int = 60

        # Downlaod file info cached by `cooldown_time`:
        remaining_time: int | None = check_chache_for_cv(cache_key, cooldown_time)
        if remaining_time is not None:
            return Response(
                {"seconds_after_retry": remaining_time},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data_preparer = UserCVDataPreparerV2(request.user.pk)
        user_cv_data: UserCVDataV2 = data_preparer.get_prepared_data()

        html_string: str = render_to_string(data_preparer.TEMPLATE_PATH, user_cv_data)
        binary_pdf_file: bytes | None = HTML(string=html_string).write_pdf()

        encoded_filename: str = urllib.parse.quote(
            f"{request.user.first_name}_{request.user.last_name}.pdf"
        )
        response = HttpResponse(binary_pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{encoded_filename}"'

        cache.set(cache_key, timezone.now(), timeout=cooldown_time)
        return response


class UserCVMailing(APIView):
    """
    Sending a CV by email (is a temporary solution).
    Full-fledged work `UserCVDownload`.
    The user can send a letter once per minute.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user_id: int = request.user.id
        cache_key: str = f"user_cv_send_mail_{user_id}"
        cooldown_time: int = 60

        # send email cached by `cooldown_time`:
        remaining_time: int | None = check_chache_for_cv(cache_key, cooldown_time)
        if remaining_time is not None:
            return Response(
                {"seconds_after_retry": remaining_time},
                status=status.HTTP_400_BAD_REQUEST,
            )

        send_mail_cv.delay(
            user_id=user_id,
            user_email=request.user.email,
            filename=f"{request.user.first_name}_{request.user.last_name}",
        )
        cache.set(cache_key, timezone.now(), timeout=cooldown_time)

        return Response(data={"detail": "success"}, status=status.HTTP_200_OK)


class PublicUserListView(ListAPIView):
    queryset = User.objects.get_active()
    serializer_class = PublicUserSerializer
    pagination_class = UsersPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = UserFilter
    permission_classes = [AllowAny]

    def get_queryset(self):
        """Оптимизация запросов для навыков и категорий"""
        return (
            super()
            .get_queryset()
            .prefetch_related(
                Prefetch(
                    "skills",
                    queryset=SkillToObject.objects.select_related(
                        "skill", "skill__category"
                    ),
                    to_attr="prefetched_skills",
                )
            )
        )

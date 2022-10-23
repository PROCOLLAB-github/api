import jwt
from core.permissions import IsOwnerOrReadOnly
from core.utils import Email
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    UpdateAPIView,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    EmailSerializer,
    PasswordSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)

User = get_user_model()


class UserList(ListCreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    permission_classes = [AllowAny]

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


class UserDetail(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    permission_classes = [IsOwnerOrReadOnly, IsAuthenticated]
    serializer_class = UserSerializer


class VerifyEmail(GenericAPIView):
    serializer_class = VerifyEmailSerializer

    def get(self, request):
        token = request.GET.get("token")
        try:
            payload = jwt.decode(jwt=token, key=settings.SECRET_KEY, algorithms=["HS256"])
            user = User.objects.get(id=payload["user_id"])
            if not user.is_active:
                user.is_active = True
                user.save()

            return Response(
                {"email": "Successfully activated"}, status=status.HTTP_200_OK
            )

        except jwt.ExpiredSignatureError:
            return Response(
                {"error": "Activate Expired"}, status=status.HTTP_400_BAD_REQUEST
            )
        except jwt.DecodeError:
            return Response({"error": "Decode error"}, status=status.HTTP_400_BAD_REQUEST)


class EmailResetPassword(UpdateAPIView):
    serializer_class = EmailSerializer

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid()

        user = User.objects.get(email=serializer.data["email"])

        token = RefreshToken.for_user(user).access_token

        relative_link = reverse("users:password_reset_sent")

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

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ResetPassword(UpdateAPIView):
    serializer_class = PasswordSerializer

    def get(self, request):
        token = request.GET.get("token")
        try:
            payload = jwt.decode(jwt=token, key=settings.SECRET_KEY, algorithms=["HS256"])
            user = User.objects.get(id=payload["user_id"])
            if not user.is_active:
                user.is_active = True
                user.save()

            return Response(
                {"email": "Successfully activated"}, status=status.HTTP_200_OK
            )
        except (jwt.ExpiredSignatureError, jwt.DecodeError):
            return False

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid()
        print(serializer.data)

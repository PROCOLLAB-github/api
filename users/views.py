import jwt
from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from rest_framework import permissions, status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView,\
    GenericAPIView

from core.utils import Email
from .serializers import UserSerializer

User = get_user_model()


class UserList(ListCreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]  # Or anon users can't register
    serializer_class = UserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)

        user = User.objects.get(email=serializer.data['email'])

        token = RefreshToken.for_user(user).access_token

        relative_link = reverse('account_email_verification_sent')
        current_site = get_current_site(request).domain
        absolute_url = 'http://' + current_site + relative_link + "?token=" + str(token)
        email_body = 'Hi, {} {}! Use link below verify your email {}'.format(
            user.first_name,
            user.last_name,
            absolute_url
        )

        data = {
            'email_body': email_body,
            'email_subject': 'Verify your email',
            'to_email': user.email
        }

        Email.send_email(data)

        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class UserDetail(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    permissions_classes = [IsAuthenticated]
    serializer_class = UserSerializer


class VerifyEmail(GenericAPIView):
    def get(self, request):
        pass
        # token = request.GET.get('token')
        # try:
        #     jwt.decode(token, )

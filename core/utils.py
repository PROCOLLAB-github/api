from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.contrib.auth.tokens import default_token_generator as token_generator
from rest_framework.mixins import CreateModelMixin
from rest_framework.response import Response
from rest_framework import status

from users.models import CustomUser


class EmailVerify(CreateModelMixin):
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        self.send_email_for_verify(request, CustomUser(serializer.data))
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def send_email_for_verify(self, request, user):
        current_site = get_current_site(request)
        context = {
            'user': user,
            'domain': current_site.domain,
            'uid': urlsafe_base64_encode(force_bytes(user.pk)),
            'token': token_generator.make_token(user),
            # 'protocol': 'http'
        }
        message = render_to_string(
            'registration/verify.html',
            context
        )
        email = EmailMessage(
            'Verify Email',
            message,
            to=[user.email]
        )
        email.send()

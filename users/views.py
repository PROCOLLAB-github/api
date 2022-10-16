from rest_framework import permissions
from rest_framework.generics import CreateAPIView
# from django.contrib.auth.models import User  # If used custom user model

from .serializers import RegisterUserSerializer
from django.contrib.auth import get_user_model

User = get_user_model()


class RegisterUserView(CreateAPIView):
    queryset = User.objects.all()

    permission_classes = [
        permissions.AllowAny  # Or anon users can't register
    ]
    serializer_class = RegisterUserSerializer

    # def post(self, request, *args, **kwargs):
    # print(request.data)
    # serializer = RegisterUserSerializer(data=request.data)

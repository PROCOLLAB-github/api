from rest_framework import permissions
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView,\
                                        RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated, IsAdminUser

from .serializers import UserSerializer
from django.contrib.auth import get_user_model

User = get_user_model()


class UserRegisterAPI(CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [
        permissions.AllowAny  # Or anon users can't register
    ]
    serializer_class = UserSerializer


class UserUpdateDeleteAPI(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    permissions_classes = [IsAuthenticated]
    serializer_class = UserSerializer

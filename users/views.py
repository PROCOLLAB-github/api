from django.contrib.auth import get_user_model
from rest_framework import permissions
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated

from users.serializers import UserSerializer

User = get_user_model()


class UserList(ListCreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]  # Or anon users can't register
    serializer_class = UserSerializer


class UserDetail(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    permissions_classes = [IsAuthenticated]
    serializer_class = UserSerializer

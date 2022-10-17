from django.contrib.auth import get_user_model
<<<<<<<<< Temporary merge branch 1
from rest_framework import permissions
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated

=========
>>>>>>>>> Temporary merge branch 2
from .serializers import UserSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework import permissions
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView


User = get_user_model()


class UserList(ListCreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]  # Or anon users can't register
    serializer_class = UserSerializer


class UserDetail(RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    permissions_classes = [IsAuthenticated]
    serializer_class = UserSerializer

from django_filters import rest_framework as filters
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from users.pagination import UsersPagination
from users.public_profile_filters import PublicProfileFilter
from users.public_profile_selectors import get_public_profiles_queryset
from users.public_profile_serializers import (
    PublicProfileDetailSerializer,
    PublicProfileListSerializer,
)


class PublicProfileListView(ListAPIView):
    """Каталог доступных профилей для авторизованных пользователей."""

    serializer_class = PublicProfileListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = UsersPagination
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_class = PublicProfileFilter

    def get_queryset(self):
        return get_public_profiles_queryset()


class PublicProfileDetailView(RetrieveAPIView):
    """Безопасный публичный профиль по идентификатору пользователя."""

    serializer_class = PublicProfileDetailSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_public_profiles_queryset(detailed=True)

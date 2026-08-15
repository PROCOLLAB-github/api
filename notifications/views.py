from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import Notification
from notifications.serializers import (
    NotificationListQuerySerializer,
    NotificationSerializer,
)


def _user_notifications(user):
    return Notification.objects.filter(recipient=user).select_related("actor")


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_serializer = NotificationListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        queryset = _user_notifications(request.user)
        unread_count = queryset.filter(read_at__isnull=True).count()
        if query_serializer.validated_data["unread"]:
            queryset = queryset.filter(read_at__isnull=True)

        paginator = LimitOffsetPagination()
        paginator.default_limit = query_serializer.validated_data["limit"]
        paginator.max_limit = 100
        page = paginator.paginate_queryset(queryset, request, view=self)
        response = paginator.get_paginated_response(
            NotificationSerializer(page, many=True).data
        )
        response.data = {
            "count": response.data["count"],
            "unread_count": unread_count,
            "next": response.data["next"],
            "previous": response.data["previous"],
            "results": response.data["results"],
        }
        return response


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unread_count = Notification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).count()
        return Response({"unread_count": unread_count})


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, notification_id):
        notification = get_object_or_404(
            Notification.objects.select_for_update().select_related("actor"),
            pk=notification_id,
            recipient=request.user,
        )
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        updated = Notification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response(
            {"updated": updated, "unread_count": 0},
            status=status.HTTP_200_OK,
        )

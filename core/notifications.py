"""Общая лента, сохраняющая совместимость прежнего API уведомлений экспертов."""

import re

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.services.registration_notifications import (
    visible_request_notifications,
)
from project_rates.notifications import (
    visible_notifications as visible_expert_notifications,
)


def unread_count(user):
    return (
        visible_expert_notifications(user).filter(read_at__isnull=True).count()
        + visible_request_notifications(user).filter(read_at__isnull=True).count()
    )


class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def get(self, request, notification_id=None):
        if notification_id is not None:
            return Response(status=405)
        experts = visible_expert_notifications(request.user)
        connections = visible_request_notifications(request.user)
        results = [
            {
                "id": f"expert_joined:{row.pk}",
                "kind": "expert_joined",
                "text": (
                    f"Эксперт {row.expert_name} ({row.expert_email}) вошел на платформу "
                    f"и принял приглашение в программу «{row.invitation.partner_program.name}»."
                ),
                "program_id": row.invitation.partner_program_id,
                "created_at": row.created_at,
                "read_at": row.read_at,
            }
            for row in experts[:100]
        ]
        results.extend(
            {
                "id": f"registration_connection:{row.pk}",
                "kind": "registration_connection",
                "text": (
                    f"Запрос на подключение сайта для программы "
                    f"«{row.request.registration.program.name}». Автор: {row.request.requester_name}."
                ),
                "program_id": row.request.registration.program_id,
                "registration_id": row.request.registration_id,
                "created_at": row.request.created_at,
                "read_at": row.read_at,
            }
            for row in connections[:100]
        )
        results.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
        return Response(
            {"unread_count": unread_count(request.user), "results": results[:100]}
        )

    def post(self, request, notification_id=None):
        if notification_id is None:
            return Response(status=405)
        match = re.fullmatch(
            r"(expert_joined|registration_connection):([1-9][0-9]{0,18})", notification_id
        )
        if not match or int(match[2]) > 2**63 - 1:
            raise Http404
        kind, pk = match[1], int(match[2])
        rows = (
            visible_expert_notifications(request.user)
            if kind == "expert_joined"
            else visible_request_notifications(request.user)
        )
        notice = get_object_or_404(rows, pk=pk)
        if notice.read_at is None:
            rows.filter(pk=pk, read_at__isnull=True).update(read_at=timezone.now())
            notice.refresh_from_db(fields=["read_at"])
        return Response(
            {
                "id": notification_id,
                "read_at": notice.read_at,
                "unread_count": unread_count(request.user),
            }
        )

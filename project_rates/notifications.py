"""Organizer receipts: accepting an invitation proves the expert is signed in."""

from functools import partial

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.services.management import person_name
from project_rates.models import ExpertJoinedNotification


def notify_expert_joined(invitation, user):
    from project_rates.tasks import send_expert_joined_notification

    for organizer in invitation.partner_program.managers.filter(is_active=True).exclude(
        pk=user.pk
    ):
        notice, created = ExpertJoinedNotification.objects.get_or_create(
            invitation=invitation,
            recipient=organizer,
            defaults={"expert_name": person_name(user), "expert_email": user.email},
        )
        if created:
            transaction.on_commit(
                partial(send_expert_joined_notification.delay, notice.pk), robust=True
            )


def visible_notifications(user):
    return (
        ExpertJoinedNotification.objects.filter(
            recipient=user,
            invitation__partner_program__managers=user,
        )
        .select_related("invitation__partner_program")
        .order_by("-created_at", "-pk")
    )


class ExpertNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def get(self, request, notification_id=None):
        if notification_id is not None:
            return Response(status=405)
        rows = visible_notifications(request.user)
        return Response(
            {
                "unread_count": rows.filter(read_at__isnull=True).count(),
                "results": [
                    {
                        "id": row.pk,
                        "text": (
                            f"Эксперт {row.expert_name} ({row.expert_email}) вошёл на платформу "
                            f"и принял приглашение в программу «{row.invitation.partner_program.name}»."
                        ),
                        "program_id": row.invitation.partner_program_id,
                        "created_at": row.created_at,
                        "read_at": row.read_at,
                    }
                    for row in rows[:100]
                ],
            }
        )

    def post(self, request, notification_id=None):
        if notification_id is None:
            return Response(status=405)
        notice = get_object_or_404(
            visible_notifications(request.user), pk=notification_id
        )
        if notice.read_at is None:
            ExpertJoinedNotification.objects.filter(
                pk=notice.pk, read_at__isnull=True
            ).update(read_at=timezone.now())
            notice.refresh_from_db(fields=["read_at"])
        return Response({"id": notice.pk, "read_at": notice.read_at})

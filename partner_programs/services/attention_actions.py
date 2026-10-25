"""Program-scoped selection, recipient preview and idempotent reminder outbox."""

import io
import logging
import uuid
from functools import partial

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.template.loader import render_to_string
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.exceptions import ValidationError

from partner_programs.models import (
    PartnerProgram,
    ProgramAttentionReminder,
    ProgramAttentionReminderBatch,
)
from partner_programs.serializers.attention import ProgramAttentionProjectSerializer
from partner_programs.serializers.attention_actions import MAX_SELECTION
from partner_programs.services.analytics import (
    participants_without_team_rows,
    participants_without_visit_rows,
    projects_awaiting_evaluation_rows,
)
from partner_programs.services.assignment_analytics import annotated_assignment_queryset
from partner_programs.services.exports import _literal_excel_cell
from partner_programs.services.management import managed_program, person_name
from partner_programs.services.solution_attention import (
    SOLUTION_AWAITING,
    solution_assignment_sources,
    solution_recipient_targets,
    solution_reminder_rows,
)
from users.models import CustomUser

logger = logging.getLogger(__name__)
SALT = "program-attention-reminder-v1"
PREVIEW_TTL = 15 * 60
MAX_ATTEMPTS = 4
LABELS = {
    "participants-without-visit": "Участники еще не заходили на платформу",
    "participants-without-team": "Участники без команды",
    "projects-awaiting-evaluation": "Работы ожидают оценивания",
    SOLUTION_AWAITING: "Решения ожидают оценивания",
}


def selected_rows(program, category, payload):
    if category == SOLUTION_AWAITING:
        return solution_reminder_rows(program, payload)
    search, selection = payload["search"], payload["selection"]
    if category == "projects-awaiting-evaluation":
        rows = projects_awaiting_evaluation_rows(program)
        if search:
            rows = rows.filter(project__name__icontains=search)
        key = "pk"
        rows = rows.order_by(F("datetime_submitted").asc(nulls_last=True), "pk")
    else:
        selector = (
            participants_without_visit_rows
            if category == "participants-without-visit"
            else participants_without_team_rows
        )
        rows = selector(program.pk)
        if search:
            rows = rows.annotate(
                search_name=Concat("user__first_name", Value(" "), "user__last_name")
            ).filter(search_name__icontains=search)
        key = "user_id"
        rows = rows.order_by(F("registered_at").asc(nulls_last=True), "user_id")
    if selection["mode"] == "selected":
        rows = rows.filter(**{f"{key}__in": selection["ids"]})
    else:
        rows = rows.exclude(**{f"{key}__in": selection["excluded_ids"]})
    if rows.count() > MAX_SELECTION:
        raise ValidationError(
            {
                "detail": f"За один раз можно выбрать до {MAX_SELECTION} строк. Уточните поиск."
            }
        )
    return list(rows)


def source_id(row, category):
    if category == SOLUTION_AWAITING:
        return row["application"]["solution_id"]
    return row.pk if category == "projects-awaiting-evaluation" else row["user_id"]


def recipient_targets(program, category, rows):
    """One recipient per real user; no inferred or newly suggested assignments."""
    if category == SOLUTION_AWAITING:
        return solution_recipient_targets(program, rows)
    if category != "projects-awaiting-evaluation":
        return [
            {
                "user_id": row["user_id"],
                "source_ids": [row["user_id"]],
                "assignment_ids": [],
            }
            for row in rows
        ]
    links = {row.project_id: row.pk for row in rows}
    targets = {}
    assignments = (
        annotated_assignment_queryset(program.pk)
        .filter(
            project_id__in=links,
            project_submitted=True,
            is_completed=False,
            expert__programs=program.pk,
        )
        .order_by("pk")
        .values("pk", "project_id", "expert__user_id")
    )
    for row in assignments:
        uid = row["expert__user_id"]
        target = targets.setdefault(
            uid, {"user_id": uid, "source_ids": [], "assignment_ids": []}
        )
        sid = links[row["project_id"]]
        if sid not in target["source_ids"]:
            target["source_ids"].append(sid)
        target["assignment_ids"].append(row["pk"])
    return list(targets.values())


def message_for(program, category, recipient, rows):
    greeting = f"{person_name(recipient)}, здравствуйте!"
    if category == "participants-without-visit":
        text = f"Вы зарегистрированы в программе «{program.name}». Зайдите на PROCOLLAB, чтобы начать участие."
        path = f"/office/program/{program.pk}"
    elif category == "participants-without-team":
        work_type = "решение" if program.solution_storage_mode == "solution" else "проект"
        text = (
            f"Вы участвуете в программе «{program.name}», но пока не состоите в команде. "
            f"Создайте {work_type} или присоединитесь к команде."
        )
        path = f"/office/program/{program.pk}/members"
    elif category == SOLUTION_AWAITING:
        names = "; ".join(f'«{row["application"]["name"]}»' for row in rows)
        text = (
            f"В программе «{program.name}» у вас остались незавершенные оценки по решениям: {names}. "
            "Завершите оценивание на PROCOLLAB."
        )
        path = f"/office/program/{program.pk}/solutions-rating"
    else:
        names = "; ".join(f"«{row.project.name}»" for row in rows)
        text = (
            f"В программе «{program.name}» у вас остались незавершенные оценки по работам: {names}. "
            "Завершите оценивание на PROCOLLAB."
        )
        path = f"/office/program/{program.pk}/projects-rating"
    return f"{greeting}\n\n{text}", path


def preview_reminder(program, category, actor, payload):
    rows = selected_rows(program, category, payload)
    targets = recipient_targets(program, category, rows)
    users = CustomUser.objects.in_bulk([t["user_id"] for t in targets])
    available = [
        t for t in targets if users.get(t["user_id"]) and users[t["user_id"]].email
    ]
    assigned_sources = {sid for t in targets for sid in t["source_ids"]}
    preview_text = ""
    if available:
        first = available[0]
        preview_text, _ = message_for(
            program,
            category,
            users[first["user_id"]],
            [r for r in rows if source_id(r, category) in first["source_ids"]],
        )
    token = (
        signing.dumps(
            {
                "request_id": str(uuid.uuid4()),
                "program_id": program.pk,
                "actor_id": actor.pk,
                "category": category,
                "source_ids": [source_id(r, category) for r in rows],
                "targets": available,
            },
            salt=SALT,
            compress=True,
        )
        if available
        else None
    )
    return {
        "token": token,
        "selected_count": len(rows),
        "recipient_count": len(available),
        "without_assignments_count": len(rows) - len(assigned_sources)
        if category in ("projects-awaiting-evaluation", SOLUTION_AWAITING)
        else 0,
        "unavailable_count": len(targets) - len(available),
        "preview_text": preview_text,
        "recipients": [
            {"user_id": t["user_id"], "full_name": person_name(users[t["user_id"]])}
            for t in available[:20]
        ],
        "expires_in": PREVIEW_TTL,
    }


def fresh_targets(program, category, ids, snapshot):
    rows = selected_rows(
        program,
        category,
        {"search": "", "selection": {"mode": "selected", "ids": ids, "excluded_ids": []}},
    )
    current = {t["user_id"]: t for t in recipient_targets(program, category, rows)}
    assignment_sources = {}
    if category == SOLUTION_AWAITING:
        assignment_sources = solution_assignment_sources(rows)
    elif category == "projects-awaiting-evaluation":
        links = {r.project_id: r.pk for r in rows}
        assignment_ids = [aid for t in current.values() for aid in t["assignment_ids"]]
        assignment_sources = {
            pk: links[pid]
            for pk, pid in annotated_assignment_queryset(program.pk)
            .filter(pk__in=assignment_ids)
            .values_list("pk", "project_id")
        }
    result = []
    for approved in snapshot:
        target = current.get(approved["user_id"])
        if not target:
            continue
        target["source_ids"] = sorted(
            set(target["source_ids"]) & set(approved["source_ids"])
        )
        target["assignment_ids"] = sorted(
            set(target["assignment_ids"]) & set(approved["assignment_ids"])
        )
        if target["source_ids"] and (
            category not in ("projects-awaiting-evaluation", SOLUTION_AWAITING)
            or target["assignment_ids"]
        ):
            # После предпросмотра назначение могли заменить. Оставляем только
            # источники утвержденных и по-прежнему незавершенных назначений.
            if category in ("projects-awaiting-evaluation", SOLUTION_AWAITING):
                target["source_ids"] = sorted(
                    {assignment_sources[aid] for aid in target["assignment_ids"]}
                )
            result.append(target)
    return rows, result


def confirm_reminder(program, category, actor, token):
    try:
        data = signing.loads(token, salt=SALT, max_age=PREVIEW_TTL)
    except signing.BadSignature:
        raise ValidationError(
            {"detail": "Предпросмотр устарел. Проверьте получателей еще раз."}
        )
    if (data.get("program_id"), data.get("category"), data.get("actor_id")) != (
        program.pk,
        category,
        actor.pk,
    ):
        raise ValidationError(
            {"detail": "Предпросмотр относится к другому списку или пользователю."}
        )
    with transaction.atomic():
        # Serialize confirmations for the same program; token UUID is the durable
        # idempotency key, including when the client loses the HTTP response.
        program = managed_program(program.pk, actor, lock=True)
        existing = ProgramAttentionReminderBatch.objects.filter(
            pk=data["request_id"]
        ).first()
        if existing:
            return existing.result
        rows, targets = fresh_targets(
            program, category, data["source_ids"], data["targets"]
        )
        users = CustomUser.objects.in_bulk([t["user_id"] for t in targets])
        targets = [
            t for t in targets if users.get(t["user_id"]) and users[t["user_id"]].email
        ]
        result = {
            "created_count": len(targets),
            "skipped_count": len(data["targets"]) - len(targets),
        }
        batch = ProgramAttentionReminderBatch.objects.create(
            id=data["request_id"],
            program=program,
            created_by=actor,
            category=category,
            result=result,
        )
        rows_by_id = {source_id(r, category): r for r in rows}
        notices = []
        for target in targets:
            text, path = message_for(
                program,
                category,
                users[target["user_id"]],
                [rows_by_id[sid] for sid in target["source_ids"]],
            )
            notices.append(
                ProgramAttentionReminder(
                    batch=batch,
                    recipient_id=target["user_id"],
                    text=text,
                    action_path=path,
                    source_ids=target["source_ids"],
                    assignment_ids=target["assignment_ids"],
                )
            )
        ProgramAttentionReminder.objects.bulk_create(notices, batch_size=500)
        transaction.on_commit(partial(queue_batch, str(batch.pk)), robust=True)
    return result


def visible_reminders(user):
    return (
        ProgramAttentionReminder.objects.filter(recipient=user)
        .select_related("batch")
        .order_by("-created_at", "-pk")
    )


def queue_batch(batch_id):
    from partner_programs.tasks import dispatch_attention_reminders

    try:
        dispatch_attention_reminders.delay(batch_id)
    except Exception:
        logger.exception("Unable to enqueue attention reminder batch %s", batch_id)


def dispatch_pending_reminders(batch_id=None):
    from partner_programs.tasks import send_attention_reminder

    rows = ProgramAttentionReminder.objects.filter(
        delivery_status="queued", emailed_at__isnull=True, attempts__lt=MAX_ATTEMPTS
    )
    if batch_id:
        rows = rows.filter(batch_id=batch_id)
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[:100])
    for pk in ids:
        try:
            send_attention_reminder.delay(pk)
        except Exception:
            logger.exception("Unable to enqueue attention reminder %s", pk)
    return len(ids)


def deliver_reminder(pk):
    error = None
    with transaction.atomic():
        notice = (
            ProgramAttentionReminder.objects.select_for_update(of=("self",))
            .select_related("batch__program", "recipient")
            .filter(pk=pk)
            .first()
        )
        if (
            not notice
            or notice.emailed_at
            or notice.attempts >= MAX_ATTEMPTS
            or notice.delivery_status == "cancelled"
        ):
            return
        program, category = notice.batch.program, notice.batch.category
        if category == SOLUTION_AWAITING:
            program = PartnerProgram.objects.select_for_update().get(pk=program.pk)
        rows, targets = fresh_targets(
            program,
            category,
            notice.source_ids,
            [
                {
                    "user_id": notice.recipient_id,
                    "source_ids": notice.source_ids,
                    "assignment_ids": notice.assignment_ids,
                }
            ],
        )
        if not targets or not notice.recipient.email:
            notice.delivery_status = "cancelled"
            notice.save(update_fields=["delivery_status"])
            return
        text, path = message_for(
            program,
            category,
            notice.recipient,
            [r for r in rows if source_id(r, category) in targets[0]["source_ids"]],
        )
        context = {
            "text": text,
            "action_url": settings.EXPERT_WORKSPACE_FRONTEND_URL.rstrip("/") + path,
        }
        notice.attempts += 1
        try:
            message = EmailMultiAlternatives(
                "Напоминание по программе | PROCOLLAB",
                render_to_string("email/attention_reminder.txt", context),
                settings.EMAIL_USER,
                [notice.recipient.email],
            )
            message.attach_alternative(
                render_to_string("email/attention_reminder.html", context), "text/html"
            )
            if not message.send():
                raise RuntimeError("Attention reminder email delivery did not complete")
        except Exception as exc:
            error = exc
            notice.delivery_status = (
                "failed" if notice.attempts >= MAX_ATTEMPTS else "queued"
            )
        else:
            notice.delivery_status = "sent"
            notice.emailed_at = timezone.now()
        notice.save(update_fields=["attempts", "delivery_status", "emailed_at"])
    if error is not None:
        raise error


def export_attention(program, category, payload):
    rows = selected_rows(program, category, payload)
    book = Workbook(write_only=True)
    sheet = book.create_sheet("Требует внимания")

    def append(values):
        sheet.append([_literal_excel_cell(sheet, value) for value in values])

    if category == "projects-awaiting-evaluation":
        users = CustomUser.objects.in_bulk(
            [r.project.leader_id for r in rows if r.project.leader_id]
        )
        append(
            [
                "ID работы в программе",
                "Проект",
                "Руководитель",
                "Email руководителя",
                "Дата сдачи",
                "Причина",
                "Назначений",
                "Выполнено",
            ]
        )
        serializer = ProgramAttentionProjectSerializer()
        for row in rows:
            leader = users.get(row.project.leader_id)
            append(
                [
                    row.pk,
                    row.project.name,
                    person_name(leader) if leader else "",
                    leader.email if leader else "",
                    row.datetime_submitted.isoformat() if row.datetime_submitted else "",
                    serializer.get_reason_label(row),
                    row.assignments_total,
                    row.assignments_completed,
                ]
            )
    else:
        users = CustomUser.objects.in_bulk([r["user_id"] for r in rows])
        append(
            [
                "ID участника",
                "Участник",
                "Email",
                "Город",
                "Дата регистрации",
                "Категория",
            ]
        )
        for row in rows:
            user = users[row["user_id"]]
            append(
                [
                    user.pk,
                    person_name(user),
                    user.email,
                    row["user__city"] or "",
                    row["registered_at"].isoformat() if row["registered_at"] else "",
                    LABELS[category],
                ]
            )
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()

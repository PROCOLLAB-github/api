from notifications.models import Notification
from notifications.services import create_notification, create_notifications


def _event_key(*parts) -> str:
    """Собирает стабильный ключ события без пользовательских данных."""
    return ":".join(str(part) for part in parts)


def _user_name(user) -> str:
    """Возвращает безопасное отображаемое имя без email и служебных полей."""
    name = user.get_full_name().strip()
    return name or "Пользователь"


def notify_project_invite_created(invite) -> None:
    """Уведомляет пользователя о новом приглашении в проект."""
    create_notification(
        recipient_id=invite.user_id,
        actor_id=invite.invited_by_id,
        notification_type=Notification.Type.PROJECT_INVITE_CREATED,
        title="Приглашение в проект",
        message=f"Вас пригласили в проект «{invite.project.name}».",
        action_url="/office/projects/invites",
        event_key=_event_key("project-invite", invite.pk, "created"),
    )


def notify_project_invite_resolved(invite, *, actor, status: str) -> None:
    """Уведомляет нужную сторону о принятии, отклонении или отзыве приглашения."""
    config = {
        "accepted": (
            invite.project.leader_id,
            Notification.Type.PROJECT_INVITE_ACCEPTED,
            "Приглашение принято",
            f"{_user_name(actor)} принял приглашение в проект «{invite.project.name}».",
            f"/office/projects/{invite.project_id}/edit?section=team",
        ),
        "declined": (
            invite.project.leader_id,
            Notification.Type.PROJECT_INVITE_DECLINED,
            "Приглашение отклонено",
            f"{_user_name(actor)} отклонил приглашение в проект «{invite.project.name}».",
            f"/office/projects/{invite.project_id}/edit?section=team",
        ),
        "revoked": (
            invite.user_id,
            Notification.Type.PROJECT_INVITE_REVOKED,
            "Приглашение отозвано",
            f"Приглашение в проект «{invite.project.name}» было отозвано.",
            "/office/projects/invites",
        ),
    }
    recipient_id, notification_type, title, message, action_url = config[status]
    create_notification(
        recipient_id=recipient_id,
        actor_id=actor.pk,
        notification_type=notification_type,
        title=title,
        message=message,
        action_url=action_url,
        event_key=_event_key("project-invite", invite.pk, status),
    )


def notify_vacancy_response_created(response) -> None:
    """Уведомляет руководителя проекта о новом отклике на вакансию."""
    vacancy = response.vacancy
    create_notification(
        recipient_id=vacancy.project.leader_id,
        actor_id=response.user_id,
        notification_type=Notification.Type.VACANCY_RESPONSE_CREATED,
        title="Новый отклик на вакансию",
        message=f"Получен отклик на вакансию «{vacancy.role}».",
        action_url=(
            f"/office/projects/{vacancy.project_id}/vacancies/" f"{vacancy.pk}/responses"
        ),
        event_key=_event_key("vacancy-response", response.pk, "created"),
    )


def notify_vacancy_response_resolved(response, *, actor, accepted: bool) -> None:
    """Уведомляет кандидата о принятии либо отклонении его отклика."""
    notification_type = (
        Notification.Type.VACANCY_RESPONSE_ACCEPTED
        if accepted
        else Notification.Type.VACANCY_RESPONSE_DECLINED
    )
    decision = "принят" if accepted else "отклонён"
    create_notification(
        recipient_id=response.user_id,
        actor_id=actor.pk,
        notification_type=notification_type,
        title=f"Отклик {decision}",
        message=f"Ваш отклик на вакансию «{response.vacancy.role}» {decision}.",
        action_url="/office/vacancies/my",
        event_key=_event_key(
            "vacancy-response",
            response.pk,
            "accepted" if accepted else "declined",
        ),
    )


def notify_team_invite_created(invite) -> None:
    """Уведомляет пользователя о новом приглашении в команду заявки."""
    create_notification(
        recipient_id=invite.user_id,
        actor_id=invite.invited_by_id,
        notification_type=Notification.Type.TEAM_INVITE_CREATED,
        title="Приглашение в команду",
        message=f"Вас пригласили в команду «{invite.team.name or 'Без названия'}».",
        action_url="/office/team-invites",
        event_key=_event_key("team-invite", invite.pk, "created"),
    )


def notify_team_invite_resolved(invite, *, actor, status: str) -> None:
    """Уведомляет капитана либо приглашённого о завершении приглашения."""
    application_id = invite.team.application_id
    config = {
        "accepted": (
            invite.team.captain_id,
            Notification.Type.TEAM_INVITE_ACCEPTED,
            "Приглашение принято",
            f"{_user_name(actor)} присоединился к команде.",
            f"/office/applications/{application_id}/team",
        ),
        "declined": (
            invite.team.captain_id,
            Notification.Type.TEAM_INVITE_DECLINED,
            "Приглашение отклонено",
            f"{_user_name(actor)} отклонил приглашение в команду.",
            f"/office/applications/{application_id}/team",
        ),
        "revoked": (
            invite.user_id,
            Notification.Type.TEAM_INVITE_REVOKED,
            "Приглашение отозвано",
            "Приглашение в команду было отозвано.",
            "/office/team-invites",
        ),
    }
    recipient_id, notification_type, title, message, action_url = config[status]
    create_notification(
        recipient_id=recipient_id,
        actor_id=actor.pk,
        notification_type=notification_type,
        title=title,
        message=message,
        action_url=action_url,
        event_key=_event_key("team-invite", invite.pk, status),
    )


def notify_application_submitted(application, *, actor) -> None:
    """Уведомляет всех менеджеров программы об отправленной заявке."""
    create_notifications(
        recipient_ids=application.program.managers.values_list("pk", flat=True),
        actor_id=actor.pk,
        notification_type=Notification.Type.APPLICATION_SUBMITTED,
        title="Новая заявка",
        message=f"Отправлена заявка в программу «{application.program.name}».",
        action_url=f"/office/program/{application.program_id}",
        event_key=_event_key("application", application.pk, "submitted"),
    )


def notify_application_status_changed(application, *, actor) -> None:
    """Уведомляет владельца заявки о подтверждённом изменении статуса."""
    if application.user_id is None:
        return
    create_notification(
        recipient_id=application.user_id,
        actor_id=actor.pk,
        notification_type=Notification.Type.APPLICATION_STATUS_CHANGED,
        title="Статус заявки изменён",
        message=f"Новый статус заявки: {application.get_status_display()}.",
        action_url=f"/office/program/{application.program_id}",
        event_key=_event_key("application", application.pk, "status", application.status),
    )


def notify_submission_submitted(submission, *, actor) -> None:
    """Уведомляет менеджеров программы об отправленном решении."""
    create_notifications(
        recipient_ids=submission.program.managers.values_list("pk", flat=True),
        actor_id=actor.pk,
        notification_type=Notification.Type.SUBMISSION_SUBMITTED,
        title="Новое решение",
        message=f"В программу «{submission.program.name}» отправлено решение.",
        action_url=f"/office/program/{submission.program_id}",
        event_key=_event_key("submission", submission.pk, "submitted"),
    )


def notify_submission_status_changed(submission, *, actor) -> None:
    """Уведомляет владельца заявки и принятых участников её команды."""
    from partner_programs.models import TeamMember

    recipient_ids = [submission.application.user_id]
    recipient_ids.extend(
        TeamMember.objects.filter(
            team__application_id=submission.application_id,
            status=TeamMember.STATUS_ACCEPTED,
        ).values_list("user_id", flat=True)
    )
    create_notifications(
        recipient_ids=recipient_ids,
        actor_id=actor.pk,
        notification_type=Notification.Type.SUBMISSION_STATUS_CHANGED,
        title="Статус решения изменён",
        message=f"Новый статус решения: {submission.get_status_display()}.",
        action_url=f"/office/program/{submission.program_id}/submission",
        event_key=_event_key("submission", submission.pk, "status", submission.status),
    )


def notify_expert_assignment_created(assignment) -> None:
    """Уведомляет эксперта о назначенной работе."""
    create_notification(
        recipient_id=assignment.expert.user_id,
        actor_id=assignment.assigned_by_id,
        notification_type=Notification.Type.EXPERT_ASSIGNMENT_CREATED,
        title="Назначена экспертиза",
        message="Вам назначено решение для оценки.",
        action_url="/office/expert/submissions",
        event_key=_event_key("expert-assignment", assignment.pk, "created"),
    )


def notify_expert_assignment_revoked(assignment, *, actor) -> None:
    """Уведомляет эксперта об отзыве назначения."""
    create_notification(
        recipient_id=assignment.expert.user_id,
        actor_id=actor.pk,
        notification_type=Notification.Type.EXPERT_ASSIGNMENT_REVOKED,
        title="Назначение отозвано",
        message="Назначение на оценивание решения было отозвано.",
        action_url="/office/expert/submissions",
        event_key=_event_key("expert-assignment", assignment.pk, "revoked"),
    )


def notify_evaluation_submitted(evaluation, *, actor) -> None:
    """Уведомляет менеджеров программы о финально отправленной оценке."""
    submission = evaluation.submission
    create_notifications(
        recipient_ids=submission.program.managers.values_list("pk", flat=True),
        actor_id=actor.pk,
        notification_type=Notification.Type.EVALUATION_SUBMITTED,
        title="Оценка отправлена",
        message=f"Эксперт отправил оценку решения «{submission.title}».",
        action_url=f"/office/analytics?programId={submission.program_id}",
        event_key=_event_key("evaluation", evaluation.pk, "submitted"),
    )


def notify_news_comment_created(comment) -> None:
    """Уведомляет владельцев источника новости о новом комментарии."""
    news = comment.news
    model = news.content_type.model
    if model == "customuser":
        recipient_ids = [news.object_id]
    elif model == "project":
        from projects.models import Project

        recipient_ids = Project.objects.filter(pk=news.object_id).values_list(
            "leader_id", flat=True
        )
    elif model == "partnerprogram":
        from partner_programs.models import PartnerProgram

        recipient_ids = PartnerProgram.objects.filter(pk=news.object_id).values_list(
            "managers__id", flat=True
        )
    else:
        return
    create_notifications(
        recipient_ids=recipient_ids,
        actor_id=comment.author_id,
        notification_type=Notification.Type.NEWS_COMMENT_CREATED,
        title="Новый комментарий",
        message="К вашей публикации добавлен комментарий.",
        action_url=f"/office/news/{news.pk}",
        event_key=_event_key("news-comment", comment.pk, "created"),
    )

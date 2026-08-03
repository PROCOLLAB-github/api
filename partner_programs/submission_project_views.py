from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partner_programs.models import Submission
from partner_programs.services.submission_project import (
    SubmissionProjectAccessError,
    SubmissionProjectStatusError,
    create_project_from_submission,
)
from projects.workspace_selectors import get_workspace_project_queryset
from projects.workspace_serializers import ProjectWorkspaceDetailSerializer


class SubmissionProjectCreateView(APIView):
    """Создает постоянный Project из отправленной версии решения."""

    permission_classes = [IsAuthenticated]

    def post(self, request, submission_id):
        visible_submissions = Submission.objects.select_related("application")
        if not (request.user.is_staff or request.user.is_superuser):
            # Accepted TeamMember может читать Submission, но постоянный Project
            # создает только владелец Application (капитан по текущему invariant).
            visible_submissions = visible_submissions.filter(
                Q(application__user=request.user)
            )
        submission = get_object_or_404(visible_submissions, pk=submission_id)

        try:
            result = create_project_from_submission(
                submission_id=submission.pk,
                actor=request.user,
            )
        except SubmissionProjectAccessError as exc:
            raise NotFound("Решение не найдено.") from exc
        except SubmissionProjectStatusError as exc:
            raise ValidationError({"status": str(exc)}) from exc

        project = get_object_or_404(
            get_workspace_project_queryset(user=request.user),
            pk=result.project.pk,
        )
        serializer = ProjectWorkspaceDetailSerializer(
            project,
            context={"request": request},
        )
        return Response(
            {"created": result.created, "project": serializer.data},
            status=(status.HTTP_201_CREATED if result.created else status.HTTP_200_OK),
        )

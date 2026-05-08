from types import SimpleNamespace

from django.contrib import admin
from django.test import TestCase
from django.test import RequestFactory
from django.utils import timezone

from courses.admin_config.answers import UserTaskAnswerAdmin
from courses.models import UserTaskAnswer, UserTaskAnswerStatus
from courses.services.answers import TaskAnswerSubmitPayload, submit_user_task_answer

from .helpers import (
    create_course,
    create_informational_task,
    create_lesson,
    create_module,
    create_text_question_task,
    create_user,
)


class SubmitUserTaskAnswerTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.course = create_course()
        self.module = create_module(self.course)
        self.lesson = create_lesson(self.module)

    def test_submit_informational_answer_creates_marker_and_allows_continue(self):
        info_task = create_informational_task(self.lesson, order=1)
        create_text_question_task(self.lesson, order=2)

        result = submit_user_task_answer(
            self.user,
            info_task,
            TaskAnswerSubmitPayload(),
        )

        answer = UserTaskAnswer.objects.get(user=self.user, task=info_task)
        self.assertEqual(answer.status, UserTaskAnswerStatus.SUBMITTED)
        self.assertTrue(answer.is_correct)
        self.assertTrue(result.can_continue)
        self.assertIsNotNone(result.next_task_id)

    def test_submit_text_question_without_review_marks_answer_correct(self):
        question_task = create_text_question_task(self.lesson, order=1)

        result = submit_user_task_answer(
            self.user,
            question_task,
            TaskAnswerSubmitPayload(answer_text="ok"),
        )

        answer = UserTaskAnswer.objects.get(user=self.user, task=question_task)
        self.assertEqual(answer.status, UserTaskAnswerStatus.SUBMITTED)
        self.assertTrue(answer.is_correct)
        self.assertTrue(result.can_continue)

    def test_submit_text_question_with_review_blocks_continue(self):
        question_task = create_text_question_task(
            self.lesson,
            order=1,
            check_type="with_review",
        )

        result = submit_user_task_answer(
            self.user,
            question_task,
            TaskAnswerSubmitPayload(answer_text="ok"),
        )

        answer = UserTaskAnswer.objects.get(user=self.user, task=question_task)
        self.assertEqual(answer.status, UserTaskAnswerStatus.PENDING_REVIEW)
        self.assertIsNone(answer.is_correct)
        self.assertFalse(result.can_continue)
        self.assertIsNone(result.next_task_id)

    def test_admin_review_recalculates_progress_after_accept(self):
        reviewer = create_user(prefix="reviewer")
        question_task = create_text_question_task(
            self.lesson,
            order=1,
            check_type="with_review",
        )
        submit_user_task_answer(
            self.user,
            question_task,
            TaskAnswerSubmitPayload(answer_text="ok"),
        )
        answer = UserTaskAnswer.objects.get(user=self.user, task=question_task)
        request = RequestFactory().post("/")
        request.user = reviewer
        form = SimpleNamespace(
            changed_data=["status", "is_correct", "reviewed_by", "reviewed_at"]
        )

        answer.status = UserTaskAnswerStatus.ACCEPTED
        answer.is_correct = True
        answer.reviewed_by = reviewer
        answer.reviewed_at = timezone.now()
        UserTaskAnswerAdmin(UserTaskAnswer, admin.site).save_model(
            request,
            answer,
            form,
            change=True,
        )

        lesson_progress = self.lesson.user_progresses.get(user=self.user)
        module_progress = self.module.user_progresses.get(user=self.user)
        course_progress = self.course.user_progresses.get(user=self.user)
        self.assertEqual(lesson_progress.percent, 100)
        self.assertEqual(module_progress.percent, 100)
        self.assertEqual(course_progress.percent, 100)

from django.test import TestCase

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

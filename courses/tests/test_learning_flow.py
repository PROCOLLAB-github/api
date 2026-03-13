from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from courses.services.learning_flow import (
    ensure_task_submission_access,
    task_completion_map,
)
from courses.services.progress import recalculate_user_progresses_for_lesson

from .helpers import (
    create_course,
    create_informational_task,
    create_lesson,
    create_module,
    create_text_question_task,
    create_user,
)


class LearningFlowTests(TestCase):
    def setUp(self):
        self.user = create_user()
        self.course = create_course()
        self.module = create_module(self.course)
        self.lesson = create_lesson(self.module)

    def test_informational_task_not_completed_before_explicit_submit(self):
        info_task = create_informational_task(self.lesson, order=1)
        question_task = create_text_question_task(self.lesson, order=2)

        completion_map = task_completion_map(self.user, [info_task, question_task])

        self.assertFalse(completion_map[info_task.id])
        self.assertFalse(completion_map[question_task.id])

    def test_submission_access_requires_current_task(self):
        info_task = create_informational_task(self.lesson, order=1)
        question_task = create_text_question_task(self.lesson, order=2)

        with self.assertRaises(PermissionDenied):
            ensure_task_submission_access(self.user, question_task)

        ensure_task_submission_access(self.user, info_task)

    def test_progress_recalculation_updates_lesson_module_and_course(self):
        info_task = create_informational_task(self.lesson, order=1)
        create_text_question_task(self.lesson, order=2)
        info_task.user_answers.create(
            user=self.user,
            status="submitted",
            is_correct=True,
        )

        recalculate_user_progresses_for_lesson(self.user, self.lesson)

        lesson_progress = self.lesson.user_progresses.get(user=self.user)
        module_progress = self.module.user_progresses.get(user=self.user)
        course_progress = self.course.user_progresses.get(user=self.user)
        self.assertEqual(lesson_progress.percent, 50)
        self.assertEqual(module_progress.percent, 50)
        self.assertEqual(course_progress.percent, 50)

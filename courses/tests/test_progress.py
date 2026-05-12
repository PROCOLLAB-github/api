from unittest import mock

from django.db import IntegrityError
from django.utils import timezone
from django.test import TestCase

from courses.models import (
    ProgressStatus,
    UserTaskAnswer,
    UserTaskAnswerStatus,
)
from courses.models.progress import (
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
)
from courses.services.progress import (
    build_progress_snapshot,
    build_progress_snapshot_from_percent,
    percent_from_counts,
    percent_from_total_percent,
    progress_payload,
    recalculate_user_progresses_for_lesson,
    status_from_percent,
    touch_course_visit,
    upsert_course_progress,
    upsert_lesson_progress,
    upsert_module_progress,
)

from .helpers import (
    create_course_context,
    create_informational_task,
    create_lesson,
    create_module,
    create_text_question_task,
    create_user,
)


class ProgressServiceTests(TestCase):
    def setUp(self):
        context = create_course_context()
        self.user = context.user
        self.course = context.course
        self.module = context.module
        self.lesson = context.lesson

    def assert_save_retry_after_concurrent_create(self, model_class, action):
        original_save = model_class.save
        first_call = True

        def save_then_raise_once(instance, *args, **kwargs):
            nonlocal first_call
            if first_call:
                first_call = False
                original_save(instance, *args, **kwargs)
                raise IntegrityError("concurrent create")
            return original_save(instance, *args, **kwargs)

        with mock.patch.object(
            model_class,
            "save",
            autospec=True,
            side_effect=save_then_raise_once,
        ):
            return action()

    def create_completed_answer(self, task, **overrides):
        values = {
            "user": self.user,
            "task": task,
            "answer_text": "ok",
            "status": UserTaskAnswerStatus.SUBMITTED,
            "is_correct": True,
        }
        values.update(overrides)
        return UserTaskAnswer.objects.create(**values)

    def test_percent_from_counts_handles_boundaries(self):
        self.assertEqual(percent_from_counts(1, 0), 0)
        self.assertEqual(percent_from_counts(0, 5), 0)
        self.assertEqual(percent_from_counts(5, 5), 100)
        self.assertEqual(percent_from_counts(2, 5), 40)

    def test_progress_payload_handles_missing_and_existing_progress(self):
        self.assertEqual(
            progress_payload(None),
            {"status": ProgressStatus.NOT_STARTED, "percent": 0},
        )
        self.assertEqual(
            progress_payload(
                UserCourseProgress(
                    status=ProgressStatus.IN_PROGRESS,
                    percent=20,
                )
            ),
            {"status": ProgressStatus.IN_PROGRESS, "percent": 20},
        )

    def test_percent_from_total_percent_uses_average_and_truncates(self):
        percent = percent_from_total_percent(200, 9)

        self.assertEqual(percent, 22)

    def test_percent_from_total_percent_handles_boundaries(self):
        self.assertEqual(percent_from_total_percent(50, 0), 0)
        self.assertEqual(percent_from_total_percent(0, 5), 0)
        self.assertEqual(percent_from_total_percent(1, 3), 0)
        self.assertEqual(percent_from_total_percent(350, 3), 100)

    def test_status_from_percent_handles_boundaries_and_blocked(self):
        self.assertEqual(status_from_percent(0), ProgressStatus.NOT_STARTED)
        self.assertEqual(status_from_percent(100), ProgressStatus.COMPLETED)
        self.assertEqual(status_from_percent(50), ProgressStatus.IN_PROGRESS)
        self.assertEqual(
            status_from_percent(0, allow_blocked=True, blocked=True),
            ProgressStatus.BLOCKED,
        )

    def test_build_progress_snapshot_marks_blocked_when_allowed(self):
        snapshot = build_progress_snapshot(
            0,
            5,
            allow_blocked=True,
            blocked=True,
        )

        self.assertEqual(snapshot.percent, 0)
        self.assertEqual(snapshot.status, ProgressStatus.BLOCKED)

    def test_build_progress_snapshot_from_percent_marks_in_progress(self):
        snapshot = build_progress_snapshot_from_percent(25)

        self.assertEqual(snapshot.percent, 25)
        self.assertEqual(snapshot.status, ProgressStatus.IN_PROGRESS)

    def test_build_progress_snapshot_from_percent_normalizes_percent(self):
        self.assertEqual(build_progress_snapshot_from_percent(-10).percent, 0)
        self.assertEqual(build_progress_snapshot_from_percent(150).percent, 100)

    def test_upsert_course_progress_creates_and_updates_progress(self):
        visited_at = timezone.now()

        created = upsert_course_progress(
            self.user,
            self.course,
            percent=30,
            touch_visit=True,
            visited_at=visited_at,
        )
        updated = upsert_course_progress(self.user, self.course, percent=100)

        self.assertEqual(created.pk, updated.pk)
        self.assertEqual(UserCourseProgress.objects.count(), 1)
        self.assertEqual(updated.status, ProgressStatus.COMPLETED)
        self.assertEqual(updated.percent, 100)
        self.assertEqual(updated.last_visit_at, visited_at)

    def test_upsert_module_progress_creates_and_updates_progress(self):
        created = upsert_module_progress(self.user, self.module, percent=25)
        updated = upsert_module_progress(self.user, self.module, percent=0)

        self.assertEqual(created.pk, updated.pk)
        self.assertEqual(UserModuleProgress.objects.count(), 1)
        self.assertEqual(updated.status, ProgressStatus.NOT_STARTED)
        self.assertEqual(updated.percent, 0)

    def test_upsert_lesson_progress_sets_current_task_and_blocked_status(self):
        task = create_text_question_task(self.lesson)

        in_progress = upsert_lesson_progress(
            self.user,
            self.lesson,
            completed_tasks=1,
            total_tasks=2,
            current_task=task,
        )
        blocked = upsert_lesson_progress(
            self.user,
            self.lesson,
            completed_tasks=0,
            total_tasks=2,
            current_task=task,
            blocked=True,
        )

        self.assertEqual(in_progress.pk, blocked.pk)
        self.assertEqual(UserLessonProgress.objects.count(), 1)
        self.assertEqual(blocked.status, ProgressStatus.BLOCKED)
        self.assertEqual(blocked.percent, 0)
        self.assertIsNone(blocked.current_task)

    def test_touch_course_visit_creates_and_updates_last_visit(self):
        first_visit = timezone.now()
        second_visit = first_visit + timezone.timedelta(minutes=5)

        created = touch_course_visit(self.user, self.course, visited_at=first_visit)
        updated = touch_course_visit(self.user, self.course, visited_at=second_visit)

        self.assertEqual(created.pk, updated.pk)
        self.assertEqual(UserCourseProgress.objects.count(), 1)
        self.assertEqual(updated.last_visit_at, second_visit)

    def test_upsert_course_progress_retries_after_concurrent_create(self):
        visited_at = timezone.now()

        progress = self.assert_save_retry_after_concurrent_create(
            UserCourseProgress,
            lambda: upsert_course_progress(
                self.user,
                self.course,
                percent=50,
                touch_visit=True,
                visited_at=visited_at,
            ),
        )

        self.assertEqual(progress.percent, 50)
        self.assertEqual(progress.last_visit_at, visited_at)
        self.assertEqual(UserCourseProgress.objects.count(), 1)

    def test_upsert_module_progress_retries_after_concurrent_create(self):
        progress = self.assert_save_retry_after_concurrent_create(
            UserModuleProgress,
            lambda: upsert_module_progress(self.user, self.module, percent=50),
        )

        self.assertEqual(progress.percent, 50)
        self.assertEqual(UserModuleProgress.objects.count(), 1)

    def test_upsert_lesson_progress_retries_after_concurrent_create(self):
        task = create_text_question_task(self.lesson)

        progress = self.assert_save_retry_after_concurrent_create(
            UserLessonProgress,
            lambda: upsert_lesson_progress(
                self.user,
                self.lesson,
                completed_tasks=1,
                total_tasks=2,
                current_task=task,
            ),
        )

        self.assertEqual(progress.percent, 50)
        self.assertEqual(progress.current_task, task)
        self.assertEqual(UserLessonProgress.objects.count(), 1)

    def test_touch_course_visit_retries_after_concurrent_create(self):
        visited_at = timezone.now()

        progress = self.assert_save_retry_after_concurrent_create(
            UserCourseProgress,
            lambda: touch_course_visit(
                self.user,
                self.course,
                visited_at=visited_at,
            ),
        )

        self.assertEqual(progress.last_visit_at, visited_at)
        self.assertEqual(UserCourseProgress.objects.count(), 1)

    def test_recalculate_progress_handles_complex_course_and_review_answer(self):
        # Arrange
        second_lesson = create_lesson(self.module, title="Second lesson", order=2)
        second_module = create_module(self.course, title="Second module", order=2)
        create_lesson(second_module, title="Other lesson", order=1)
        create_text_question_task(second_lesson, title="Later question", order=1)
        reviewer = create_user(prefix="reviewer")

        info_task = create_informational_task(self.lesson, order=1)
        first_task = create_text_question_task(self.lesson, title="First", order=2)
        review_task = create_text_question_task(
            self.lesson,
            title="Review",
            order=3,
            check_type="with_review",
        )
        fourth_task = create_text_question_task(self.lesson, title="Fourth", order=4)
        fifth_task = create_text_question_task(self.lesson, title="Fifth", order=5)

        self.create_completed_answer(
            task=info_task,
            answer_text="",
            status=UserTaskAnswerStatus.SUBMITTED,
            is_correct=True,
        )
        self.create_completed_answer(task=first_task)
        review_answer = UserTaskAnswer.objects.create(
            user=self.user,
            task=review_task,
            answer_text="needs review",
            status=UserTaskAnswerStatus.PENDING_REVIEW,
        )

        # Act
        recalculate_user_progresses_for_lesson(self.user, self.lesson)

        # Assert
        lesson_progress = self.lesson.user_progresses.get(user=self.user)
        module_progress = self.module.user_progresses.get(user=self.user)
        course_progress = self.course.user_progresses.get(user=self.user)
        self.assertEqual(lesson_progress.percent, 40)
        self.assertEqual(lesson_progress.status, ProgressStatus.IN_PROGRESS)
        self.assertEqual(lesson_progress.current_task, review_task)
        self.assertEqual(module_progress.percent, 20)
        self.assertEqual(course_progress.percent, 13)

        # Act
        review_answer.status = UserTaskAnswerStatus.ACCEPTED
        review_answer.is_correct = True
        review_answer.reviewed_by = reviewer
        review_answer.reviewed_at = timezone.now()
        review_answer.save()
        for task in (fourth_task, fifth_task):
            self.create_completed_answer(task)

        recalculate_user_progresses_for_lesson(self.user, self.lesson)

        # Assert
        lesson_progress.refresh_from_db()
        module_progress.refresh_from_db()
        course_progress.refresh_from_db()
        self.assertEqual(lesson_progress.percent, 100)
        self.assertEqual(lesson_progress.status, ProgressStatus.COMPLETED)
        self.assertIsNone(lesson_progress.current_task)
        self.assertEqual(module_progress.percent, 50)
        self.assertEqual(course_progress.percent, 33)

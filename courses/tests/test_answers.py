from types import SimpleNamespace

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test import RequestFactory
from django.utils import timezone

from courses.admin_config.answers import UserTaskAnswerAdmin
from courses.models import (
    CourseTaskAnswerType,
    CourseTaskOption,
    UserTaskAnswer,
    UserTaskAnswerFile,
    UserTaskAnswerOption,
    UserTaskAnswerStatus,
)
from courses.models.constants import DEFAULT_MAX_FILES_PER_ANSWER
from courses.services.answers import TaskAnswerSubmitPayload, submit_user_task_answer

from .helpers import (
    create_choice_question_task,
    create_course_context,
    create_files_question_task,
    create_informational_task,
    create_text_and_files_question_task,
    create_text_question_task,
    create_user,
    create_user_file,
)


class SubmitUserTaskAnswerTests(TestCase):
    def setUp(self):
        context = create_course_context()
        self.user = context.user
        self.course = context.course
        self.module = context.module
        self.lesson = context.lesson

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


class UserTaskAnswerModelValidationTests(TestCase):
    def setUp(self):
        context = create_course_context()
        self.user = context.user
        self.course = context.course
        self.module = context.module
        self.lesson = context.lesson

    def assertValidationErrorFields(self, error, expected_fields):
        self.assertEqual(
            set(error.exception.message_dict),
            set(expected_fields),
        )

    def build_answer(self, task, **overrides):
        values = {
            "user": self.user,
            "task": task,
        }
        values.update(overrides)
        return UserTaskAnswer(**values)

    def test_informational_answer_forbids_text_review_fields_and_review_status(self):
        reviewer = create_user(prefix="reviewer")
        info_task = create_informational_task(self.lesson)
        answer = self.build_answer(
            task=info_task,
            answer_text="not needed",
            status=UserTaskAnswerStatus.ACCEPTED,
            review_comment="checked",
            reviewed_by=reviewer,
            reviewed_at=timezone.now(),
        )

        with self.assertRaises(ValidationError) as error:
            answer.full_clean()

        self.assertValidationErrorFields(
            error,
            ["answer_text", "status", "review_comment", "reviewed_by", "reviewed_at"],
        )

    def test_text_answers_require_text(self):
        text_task = create_text_question_task(self.lesson, order=1)
        text_and_files_task = create_text_and_files_question_task(self.lesson, order=2)

        for task in (text_task, text_and_files_task):
            with self.subTest(answer_type=task.answer_type):
                answer = self.build_answer(task, answer_text=" ")

                with self.assertRaises(ValidationError) as error:
                    answer.full_clean()

                self.assertValidationErrorFields(error, ["answer_text"])

    def test_non_text_answers_forbid_text(self):
        attachment = create_user_file(self.user)
        files_task = create_files_question_task(
            self.lesson,
            attachment_file=attachment,
            order=1,
        )
        single_choice_task, _ = create_choice_question_task(
            self.lesson,
            title="Single choice",
            order=2,
            answer_type=CourseTaskAnswerType.SINGLE_CHOICE,
            options=[("Correct", True), ("Wrong", False)],
        )
        multiple_choice_task, _ = create_choice_question_task(
            self.lesson,
            title="Multiple choice",
            order=3,
            answer_type=CourseTaskAnswerType.MULTIPLE_CHOICE,
            options=[("Correct 1", True), ("Correct 2", True), ("Wrong", False)],
        )

        for task in (files_task, single_choice_task, multiple_choice_task):
            with self.subTest(answer_type=task.answer_type):
                answer = self.build_answer(
                    task,
                    answer_text="not allowed",
                )

                with self.assertRaises(ValidationError) as error:
                    answer.full_clean()

                self.assertValidationErrorFields(error, ["answer_text"])

    def test_pending_review_is_forbidden_for_task_without_review(self):
        task = create_text_question_task(self.lesson)
        answer = self.build_answer(
            task=task,
            answer_text="ok",
            status=UserTaskAnswerStatus.PENDING_REVIEW,
        )

        with self.assertRaises(ValidationError) as error:
            answer.full_clean()

        self.assertValidationErrorFields(error, ["status"])

    def test_reviewed_by_and_reviewed_at_must_be_filled_together(self):
        reviewer = create_user(prefix="reviewer")
        task = create_text_question_task(self.lesson, check_type="with_review")
        answer = self.build_answer(
            task=task,
            answer_text="ok",
            reviewed_by=reviewer,
        )

        with self.assertRaises(ValidationError) as error:
            answer.full_clean()

        self.assertValidationErrorFields(error, ["reviewed_by", "reviewed_at"])

    def test_checked_answer_with_review_requires_reviewer(self):
        task = create_text_question_task(self.lesson, check_type="with_review")
        answer = self.build_answer(
            task=task,
            answer_text="ok",
            status=UserTaskAnswerStatus.ACCEPTED,
        )

        with self.assertRaises(ValidationError) as error:
            answer.full_clean()

        self.assertValidationErrorFields(error, ["reviewed_by", "reviewed_at"])


class UserTaskAnswerOptionModelValidationTests(TestCase):
    def setUp(self):
        context = create_course_context()
        self.user = context.user
        self.course = context.course
        self.module = context.module
        self.lesson = context.lesson

    def test_selected_option_must_belong_to_answer_task(self):
        first_task, _ = create_choice_question_task(
            self.lesson,
            title="First choice",
            order=1,
            answer_type=CourseTaskAnswerType.SINGLE_CHOICE,
            options=[("A", True), ("B", False)],
        )
        second_task, second_options = create_choice_question_task(
            self.lesson,
            title="Second choice",
            order=2,
            answer_type=CourseTaskAnswerType.SINGLE_CHOICE,
            options=[("C", True), ("D", False)],
        )
        answer = UserTaskAnswer.objects.create(user=self.user, task=first_task)

        selected_option = UserTaskAnswerOption(
            answer=answer,
            option=second_options[0],
        )

        with self.assertRaises(ValidationError) as error:
            selected_option.full_clean()

        self.assertIn("option", error.exception.message_dict)

    def test_selected_option_is_allowed_only_for_choice_answers(self):
        task = create_text_question_task(self.lesson)
        answer = UserTaskAnswer.objects.create(
            user=self.user,
            task=task,
            answer_text="ok",
        )
        option = CourseTaskOption(task=task, order=1, text="Invalid option")
        CourseTaskOption.objects.bulk_create([option])
        option.refresh_from_db()

        selected_option = UserTaskAnswerOption(answer=answer, option=option)

        with self.assertRaises(ValidationError) as error:
            selected_option.full_clean()

        self.assertIn("answer", error.exception.message_dict)

    def test_single_choice_answer_allows_only_one_selected_option(self):
        task, options = create_choice_question_task(
            self.lesson,
            title="Single choice",
            order=1,
            answer_type=CourseTaskAnswerType.SINGLE_CHOICE,
            options=[("A", True), ("B", False)],
        )
        answer = UserTaskAnswer.objects.create(user=self.user, task=task)
        UserTaskAnswerOption.objects.create(answer=answer, option=options[0])

        with self.assertRaises(ValidationError) as error:
            UserTaskAnswerOption.objects.create(answer=answer, option=options[1])

        self.assertIn("answer", error.exception.message_dict)


class UserTaskAnswerFileModelValidationTests(TestCase):
    def setUp(self):
        context = create_course_context()
        self.user = context.user
        self.course = context.course
        self.module = context.module
        self.lesson = context.lesson

    def test_answer_files_are_allowed_only_for_file_answer_types(self):
        task = create_text_question_task(self.lesson)
        answer = UserTaskAnswer.objects.create(
            user=self.user,
            task=task,
            answer_text="ok",
        )
        user_file = create_user_file(self.user)
        answer_file = UserTaskAnswerFile(answer=answer, file=user_file)

        with self.assertRaises(ValidationError) as error:
            answer_file.full_clean()

        self.assertIn("answer", error.exception.message_dict)

    def test_answer_file_save_fills_file_name_and_size(self):
        attachment = create_user_file(self.user, name="task-template")
        task = create_files_question_task(
            self.lesson,
            attachment_file=attachment,
        )
        answer = UserTaskAnswer.objects.create(user=self.user, task=task)
        user_file = create_user_file(
            self.user,
            name="solution",
            extension="txt",
            mime_type="text/plain",
            size=2048,
        )

        answer_file = UserTaskAnswerFile.objects.create(answer=answer, file=user_file)

        self.assertEqual(answer_file.file_name, user_file.name)
        self.assertEqual(answer_file.file_size, user_file.size)

    def test_answer_files_are_limited_per_answer(self):
        attachment = create_user_file(self.user, name="task-template")
        task = create_files_question_task(
            self.lesson,
            attachment_file=attachment,
        )
        answer = UserTaskAnswer.objects.create(user=self.user, task=task)
        existing_files = [
            UserTaskAnswerFile(
                answer=answer,
                file=create_user_file(self.user, name=f"solution-{index}"),
            )
            for index in range(DEFAULT_MAX_FILES_PER_ANSWER)
        ]
        UserTaskAnswerFile.objects.bulk_create(existing_files)
        extra_file = create_user_file(self.user, name="extra-solution")

        with self.assertRaises(ValidationError) as error:
            UserTaskAnswerFile.objects.create(answer=answer, file=extra_file)

        self.assertIn("answer", error.exception.message_dict)

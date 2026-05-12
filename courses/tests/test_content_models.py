from django.core.exceptions import ValidationError
from django.test import TestCase

from courses.models import (
    CourseModule,
    CourseTask,
    CourseTaskAnswerType,
    CourseTaskCheckType,
    CourseTaskContentStatus,
    CourseTaskInformationalType,
    CourseTaskKind,
    CourseTaskOption,
    CourseTaskQuestionType,
)

from .helpers import (
    create_course_context,
    create_informational_task,
    create_text_question_task,
    create_user_file,
)


class CourseContentModelValidationTests(TestCase):
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

    def build_informational_task(self, informational_type, **overrides):
        values = {
            "lesson": self.lesson,
            "title": "Informational task",
            "status": CourseTaskContentStatus.DRAFT,
            "task_kind": CourseTaskKind.INFORMATIONAL,
            "informational_type": informational_type,
            "order": 1,
        }
        values.update(overrides)
        return CourseTask(**values)

    def build_question_task(self, question_type, **overrides):
        values = {
            "lesson": self.lesson,
            "title": "Question task",
            "status": CourseTaskContentStatus.DRAFT,
            "task_kind": CourseTaskKind.QUESTION,
            "question_type": question_type,
            "answer_type": CourseTaskAnswerType.TEXT,
            "check_type": CourseTaskCheckType.WITHOUT_REVIEW,
            "order": 1,
        }
        values.update(overrides)
        return CourseTask(**values)

    def test_module_avatar_must_be_image_file(self):
        avatar = create_user_file(
            self.user,
            name="avatar",
            extension="pdf",
            mime_type="application/pdf",
        )
        module = CourseModule(
            course=self.course,
            title="Invalid avatar module",
            avatar_file=avatar,
            start_date=self.module.start_date,
            status=self.module.status,
            order=2,
        )

        with self.assertRaises(ValidationError) as error:
            module.full_clean()

        self.assertValidationErrorFields(error, ["avatar_file"])

    def test_task_image_file_must_be_image(self):
        image = create_user_file(
            self.user,
            name="image",
            extension="pdf",
            mime_type="application/pdf",
        )
        task = self.build_question_task(
            CourseTaskQuestionType.TEXT,
            body_text="Question body",
            image_file=image,
        )

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["image_file"])

    def test_informational_video_text_requires_body_text_and_video_url(self):
        task = self.build_informational_task(CourseTaskInformationalType.VIDEO_TEXT)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["body_text", "video_url"])

    def test_informational_text_requires_body_text(self):
        task = self.build_informational_task(CourseTaskInformationalType.TEXT)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["body_text"])

    def test_informational_text_image_requires_body_text_and_image(self):
        task = self.build_informational_task(CourseTaskInformationalType.TEXT_IMAGE)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["body_text", "image_file"])

    def test_pending_image_upload_satisfies_image_source_requirement(self):
        task = self.build_informational_task(
            CourseTaskInformationalType.TEXT_IMAGE,
            body_text="Text with uploaded image",
        )
        task._has_pending_image_upload = True

        task.full_clean()

    def test_question_image_text_requires_body_text_and_image(self):
        task = self.build_question_task(CourseTaskQuestionType.IMAGE_TEXT)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["body_text", "image_file"])

    def test_question_video_requires_video_url(self):
        task = self.build_question_task(CourseTaskQuestionType.VIDEO)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["video_url"])

    def test_question_image_requires_image(self):
        task = self.build_question_task(CourseTaskQuestionType.IMAGE)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["image_file"])

    def test_question_text_file_requires_body_text_and_attachment(self):
        task = self.build_question_task(
            CourseTaskQuestionType.TEXT_FILE,
            answer_type=CourseTaskAnswerType.FILES,
        )

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["body_text", "attachment_file"])

    def test_pending_attachment_upload_satisfies_attachment_source_requirement(self):
        task = self.build_question_task(
            CourseTaskQuestionType.TEXT_FILE,
            answer_type=CourseTaskAnswerType.FILES,
            body_text="Attach file",
        )
        task._has_pending_attachment_upload = True

        task.full_clean()

    def test_question_text_requires_body_text(self):
        task = self.build_question_task(CourseTaskQuestionType.TEXT)

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["body_text"])

    def test_published_choice_task_requires_correct_option(self):
        task = CourseTask.objects.create(
            lesson=self.lesson,
            title="Choice question",
            status=CourseTaskContentStatus.DRAFT,
            task_kind=CourseTaskKind.QUESTION,
            question_type=CourseTaskQuestionType.TEXT,
            answer_type=CourseTaskAnswerType.MULTIPLE_CHOICE,
            check_type=CourseTaskCheckType.WITHOUT_REVIEW,
            body_text="Choose",
            order=1,
        )
        CourseTaskOption.objects.create(task=task, text="Wrong", order=1)
        task.status = CourseTaskContentStatus.PUBLISHED

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["status"])

    def test_published_single_choice_task_requires_one_correct_option(self):
        task = CourseTask.objects.create(
            lesson=self.lesson,
            title="Single choice question",
            status=CourseTaskContentStatus.DRAFT,
            task_kind=CourseTaskKind.QUESTION,
            question_type=CourseTaskQuestionType.TEXT,
            answer_type=CourseTaskAnswerType.SINGLE_CHOICE,
            check_type=CourseTaskCheckType.WITHOUT_REVIEW,
            body_text="Choose",
            order=1,
        )
        CourseTaskOption.objects.bulk_create(
            [
                CourseTaskOption(task=task, text="Correct 1", is_correct=True, order=1),
                CourseTaskOption(task=task, text="Correct 2", is_correct=True, order=2),
            ]
        )
        task.status = CourseTaskContentStatus.PUBLISHED

        with self.assertRaises(ValidationError) as error:
            task.full_clean()

        self.assertValidationErrorFields(error, ["status"])

    def test_task_option_is_forbidden_for_informational_task(self):
        task = create_informational_task(self.lesson)
        option = CourseTaskOption(task=task, text="Invalid", order=1)

        with self.assertRaises(ValidationError) as error:
            option.full_clean()

        self.assertValidationErrorFields(error, ["task"])

    def test_task_option_is_allowed_only_for_choice_answer_types(self):
        task = create_text_question_task(self.lesson)
        option = CourseTaskOption(task=task, text="Invalid", order=1)

        with self.assertRaises(ValidationError) as error:
            option.full_clean()

        self.assertValidationErrorFields(error, ["task"])

    def test_single_choice_task_allows_only_one_correct_option(self):
        task = CourseTask.objects.create(
            lesson=self.lesson,
            title="Single choice draft",
            status=CourseTaskContentStatus.DRAFT,
            task_kind=CourseTaskKind.QUESTION,
            question_type=CourseTaskQuestionType.TEXT,
            answer_type=CourseTaskAnswerType.SINGLE_CHOICE,
            check_type=CourseTaskCheckType.WITHOUT_REVIEW,
            body_text="Choose",
            order=1,
        )
        CourseTaskOption.objects.create(
            task=task,
            text="Correct 1",
            is_correct=True,
            order=1,
        )
        option = CourseTaskOption(
            task=task,
            text="Correct 2",
            is_correct=True,
            order=2,
        )

        with self.assertRaises(ValidationError) as error:
            option.full_clean()

        self.assertValidationErrorFields(error, ["is_correct"])

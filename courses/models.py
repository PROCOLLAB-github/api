from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from files.models import UserFile
from partner_programs.models import PartnerProgram


class CourseAccessType(models.TextChoices):
    ALL_USERS = "all_users", "Для всех пользователей"
    PROGRAM_MEMBERS = "program_members", "Для участников программы"
    SUBSCRIPTION_STUB = "subscription_stub", "По подписке"


class CourseContentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    PUBLISHED = "published", "Опубликован"
    COMPLETED = "completed", "Завершен"


class CourseModuleContentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    PUBLISHED = "published", "Опубликован"


class CourseLessonContentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    PUBLISHED = "published", "Опубликован"


class CourseTaskContentStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    PUBLISHED = "published", "Опубликован"


class CourseTaskKind(models.TextChoices):
    INFORMATIONAL = "informational", "Информационное"
    QUESTION = "question", "Вопрос/ответ"


class CourseTaskCheckType(models.TextChoices):
    WITHOUT_REVIEW = "without_review", "Без проверки"
    WITH_REVIEW = "with_review", "С проверкой"


class CourseTaskInformationalType(models.TextChoices):
    VIDEO_TEXT = "video_text", "Видео и текст"
    TEXT = "text", "Текст"
    TEXT_IMAGE = "text_image", "Текст и изображение"


class CourseTaskQuestionType(models.TextChoices):
    IMAGE_TEXT = "image_text", "Изображение и текст"
    VIDEO = "video", "Видео"
    IMAGE = "image", "Изображение"
    TEXT_FILE = "text_file", "Текст с файлом"
    TEXT = "text", "Текст"


class CourseTaskAnswerType(models.TextChoices):
    TEXT = "text", "Текст"
    TEXT_AND_FILES = "text_and_files", "Текст и загрузка файла"
    FILES = "files", "Загрузка файла"
    MULTIPLE_CHOICE = (
        "multiple_choice",
        "Выбор одного или нескольких вариантов ответа",
    )
    SINGLE_CHOICE = "single_choice", "Выбор одного варианта ответа"


class UserTaskAnswerStatus(models.TextChoices):
    SUBMITTED = "submitted", "Отправлено"
    PENDING_REVIEW = "pending_review", "Ожидает проверки"
    ACCEPTED = "accepted", "Принято"
    REJECTED = "rejected", "Отклонено"


class Course(models.Model):
    title = models.CharField(
        max_length=45,
        verbose_name="Название курса",
    )
    description = models.TextField(
        blank=True,
        default="",
        validators=[MaxLengthValidator(600)],
        verbose_name="Описание",
    )
    access_type = models.CharField(
        max_length=32,
        choices=CourseAccessType.choices,
        default=CourseAccessType.ALL_USERS,
        verbose_name="Тип доступа",
    )
    partner_program = models.ForeignKey(
        PartnerProgram,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
        verbose_name="Программа",
    )
    avatar_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_avatars",
        verbose_name="Аватар курса",
    )
    card_cover_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_card_covers",
        verbose_name="Обложка карточки курса",
    )
    header_cover_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_header_covers",
        verbose_name="Обложка шапки курса",
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата старта",
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Дата окончания",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseContentStatus.choices,
        default=CourseContentStatus.DRAFT,
        verbose_name="Статус курса",
    )
    is_completed = models.BooleanField(
        default=False,
        verbose_name="Курс завершен",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата завершения",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Курс"
        verbose_name_plural = "Курсы"
        ordering = ("-datetime_created",)
        constraints = [
            models.CheckConstraint(
                check=~Q(access_type=CourseAccessType.PROGRAM_MEMBERS)
                | Q(partner_program__isnull=False),
                name="courses_program_members_requires_program",
            ),
            models.CheckConstraint(
                check=(
                    Q(start_date__isnull=True, end_date__isnull=True)
                    | Q(start_date__isnull=False, end_date__isnull=False)
                ),
                name="courses_dates_must_be_set_together",
            ),
            models.CheckConstraint(
                check=Q(start_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="courses_end_date_gte_start_date",
            ),
            models.CheckConstraint(
                check=~Q(status=CourseContentStatus.COMPLETED)
                | Q(is_completed=True),
                name="courses_completed_status_implies_flag",
            ),
            models.CheckConstraint(
                check=Q(is_completed=False)
                | Q(status=CourseContentStatus.COMPLETED),
                name="courses_completed_flag_implies_status",
            ),
        ]

    def __str__(self):
        return f"Course<{self.id}> - {self.title}"

    def is_completed_by_date(self) -> bool:
        if not self.end_date:
            return False
        return timezone.localdate() > self.end_date

    def clean(self):
        super().clean()

        if (
            self.access_type == CourseAccessType.PROGRAM_MEMBERS
            and self.partner_program_id is None
        ):
            raise ValidationError(
                {"partner_program": "Поле обязательно для доступа участникам программы."}
            )

        has_start_date = self.start_date is not None
        has_end_date = self.end_date is not None
        if has_start_date != has_end_date:
            raise ValidationError(
                {
                    "start_date": "Дата старта и дата окончания должны быть заполнены вместе.",
                    "end_date": "Дата старта и дата окончания должны быть заполнены вместе.",
                }
            )

        if has_start_date and has_end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "Дата окончания не может быть раньше даты старта."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()

        if self.status == CourseContentStatus.COMPLETED:
            self.is_completed = True
            if not self.completed_at:
                self.completed_at = timezone.now()

        if self.is_completed and self.status != CourseContentStatus.COMPLETED:
            self.status = CourseContentStatus.COMPLETED
            if not self.completed_at:
                self.completed_at = timezone.now()

        super().save(*args, **kwargs)


class CourseModule(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
        verbose_name="Курс",
    )
    title = models.CharField(
        max_length=40,
        verbose_name="Название модуля",
    )
    avatar_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_module_avatars",
        verbose_name="Аватар модуля",
    )
    start_date = models.DateField(
        verbose_name="Дата старта модуля",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseModuleContentStatus.choices,
        default=CourseModuleContentStatus.DRAFT,
        verbose_name="Статус модуля",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Модуль курса"
        verbose_name_plural = "Модули курса"
        ordering = ("course_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("course", "order"),
                name="courses_module_unique_course_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_module_order_gte_1",
            ),
        ]

    def __str__(self):
        return f"CourseModule<{self.id}> - {self.title}"


class CourseLesson(models.Model):
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        related_name="lessons",
        verbose_name="Модуль курса",
    )
    title = models.CharField(
        max_length=45,
        verbose_name="Название урока",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseLessonContentStatus.choices,
        default=CourseLessonContentStatus.DRAFT,
        verbose_name="Статус урока",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Урок курса"
        verbose_name_plural = "Уроки курса"
        ordering = ("module_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("module", "order"),
                name="courses_lesson_unique_module_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_lesson_order_gte_1",
            ),
        ]

    def __str__(self):
        return f"CourseLesson<{self.id}> - {self.title}"


class CourseTask(models.Model):
    lesson = models.ForeignKey(
        CourseLesson,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="Урок курса",
    )
    title = models.CharField(
        max_length=255,
        verbose_name="Название задания",
    )
    body_text = models.TextField(
        blank=True,
        default="",
        verbose_name="Текст",
    )
    status = models.CharField(
        max_length=16,
        choices=CourseTaskContentStatus.choices,
        default=CourseTaskContentStatus.DRAFT,
        verbose_name="Статус задания",
    )
    task_kind = models.CharField(
        max_length=16,
        choices=CourseTaskKind.choices,
        verbose_name="Тип задания",
    )
    check_type = models.CharField(
        max_length=16,
        choices=CourseTaskCheckType.choices,
        null=True,
        blank=True,
        verbose_name="Тип проверки",
    )
    informational_type = models.CharField(
        max_length=24,
        choices=CourseTaskInformationalType.choices,
        null=True,
        blank=True,
        verbose_name="Тип информационного задания",
    )
    question_type = models.CharField(
        max_length=24,
        choices=CourseTaskQuestionType.choices,
        null=True,
        blank=True,
        verbose_name="Тип вопроса",
    )
    answer_type = models.CharField(
        max_length=24,
        choices=CourseTaskAnswerType.choices,
        null=True,
        blank=True,
        verbose_name="Тип ответа",
    )
    video_url = models.URLField(
        null=True,
        blank=True,
        verbose_name="Ссылка на видео",
    )
    image_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_task_images",
        verbose_name="Изображение",
    )
    attachment_file = models.ForeignKey(
        UserFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_task_attachments",
        verbose_name="Файл",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Задание курса"
        verbose_name_plural = "Задания курса"
        ordering = ("lesson_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("lesson", "order"),
                name="courses_task_unique_lesson_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_task_order_gte_1",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.INFORMATIONAL)
                | Q(informational_type__isnull=False),
                name="courses_task_info_requires_info_type",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.QUESTION)
                | (
                    Q(question_type__isnull=False)
                    & Q(answer_type__isnull=False)
                    & Q(check_type__isnull=False)
                ),
                name="courses_task_question_requires_types",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.INFORMATIONAL)
                | (
                    Q(question_type__isnull=True)
                    & Q(answer_type__isnull=True)
                    & Q(check_type__isnull=True)
                ),
                name="courses_task_info_forbids_question_fields",
            ),
            models.CheckConstraint(
                check=~Q(task_kind=CourseTaskKind.QUESTION)
                | Q(informational_type__isnull=True),
                name="courses_task_question_forbids_info_type",
            ),
        ]

    def __str__(self):
        return f"CourseTask<{self.id}> - {self.title}"

    @staticmethod
    def _require_non_blank(value: str | None) -> bool:
        return bool(value and value.strip())

    def clean(self):
        super().clean()

        errors = {}

        if self.task_kind == CourseTaskKind.INFORMATIONAL:
            if self.informational_type == CourseTaskInformationalType.VIDEO_TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = "Поле обязательно для типа 'Видео и текст'."
                if not self._require_non_blank(self.video_url):
                    errors["video_url"] = "Поле обязательно для типа 'Видео и текст'."
            elif self.informational_type == CourseTaskInformationalType.TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = "Поле обязательно для типа 'Текст'."
            elif self.informational_type == CourseTaskInformationalType.TEXT_IMAGE:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = (
                        "Поле обязательно для типа 'Текст и изображение'."
                    )
                if self.image_file_id is None:
                    errors["image_file"] = (
                        "Поле обязательно для типа 'Текст и изображение'."
                    )

        if self.task_kind == CourseTaskKind.QUESTION:
            if self.question_type == CourseTaskQuestionType.IMAGE_TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = (
                        "Поле обязательно для типа вопроса 'Изображение и текст'."
                    )
                if self.image_file_id is None:
                    errors["image_file"] = (
                        "Поле обязательно для типа вопроса 'Изображение и текст'."
                    )
            elif self.question_type == CourseTaskQuestionType.VIDEO:
                if not self._require_non_blank(self.video_url):
                    errors["video_url"] = "Поле обязательно для типа вопроса 'Видео'."
            elif self.question_type == CourseTaskQuestionType.IMAGE:
                if self.image_file_id is None:
                    errors["image_file"] = (
                        "Поле обязательно для типа вопроса 'Изображение'."
                    )
            elif self.question_type == CourseTaskQuestionType.TEXT_FILE:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = (
                        "Поле обязательно для типа вопроса 'Текст с файлом'."
                    )
                if self.attachment_file_id is None:
                    errors["attachment_file"] = (
                        "Поле обязательно для типа вопроса 'Текст с файлом'."
                    )
            elif self.question_type == CourseTaskQuestionType.TEXT:
                if not self._require_non_blank(self.body_text):
                    errors["body_text"] = "Поле обязательно для типа вопроса 'Текст'."

        if errors:
            raise ValidationError(errors)


class CourseTaskOption(models.Model):
    task = models.ForeignKey(
        CourseTask,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="Задание",
    )
    text = models.CharField(
        max_length=500,
        verbose_name="Текст варианта",
    )
    is_correct = models.BooleanField(
        default=False,
        verbose_name="Правильный вариант",
    )
    order = models.PositiveIntegerField(
        default=1,
        verbose_name="Порядковый номер",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Вариант ответа задания"
        verbose_name_plural = "Варианты ответов задания"
        ordering = ("task_id", "order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("task", "order"),
                name="courses_task_option_unique_task_order",
            ),
            models.CheckConstraint(
                check=Q(order__gte=1),
                name="courses_task_option_order_gte_1",
            ),
        ]

    def __str__(self):
        return f"CourseTaskOption<{self.id}> - task={self.task_id}"

    def clean(self):
        super().clean()
        if self.task.answer_type not in (
            CourseTaskAnswerType.SINGLE_CHOICE,
            CourseTaskAnswerType.MULTIPLE_CHOICE,
        ):
            raise ValidationError(
                {
                    "task": (
                        "Варианты ответа доступны только для типов "
                        "'single_choice' и 'multiple_choice'."
                    )
                }
            )


class UserTaskAnswer(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_task_answers",
        verbose_name="Пользователь",
    )
    task = models.ForeignKey(
        CourseTask,
        on_delete=models.CASCADE,
        related_name="user_answers",
        verbose_name="Задание",
    )
    status = models.CharField(
        max_length=20,
        choices=UserTaskAnswerStatus.choices,
        default=UserTaskAnswerStatus.SUBMITTED,
        verbose_name="Статус ответа",
    )
    answer_text = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="Текст ответа",
    )
    is_correct = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="Ответ корректен",
    )
    submitted_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Дата и время отправки",
    )
    review_comment = models.TextField(
        blank=True,
        default="",
        verbose_name="Комментарий проверяющего",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_course_task_answers",
        verbose_name="Проверил",
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата и время проверки",
    )
    datetime_created = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
    )
    datetime_updated = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления",
    )

    class Meta:
        verbose_name = "Ответ пользователя на задание"
        verbose_name_plural = "Ответы пользователей на задания"
        ordering = ("-submitted_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "task"),
                name="courses_user_task_answer_unique_user_task",
            ),
        ]

    def __str__(self):
        return f"UserTaskAnswer<{self.id}> - user={self.user_id} task={self.task_id}"


class UserTaskAnswerOption(models.Model):
    answer = models.ForeignKey(
        UserTaskAnswer,
        on_delete=models.CASCADE,
        related_name="selected_options",
        verbose_name="Ответ пользователя",
    )
    option = models.ForeignKey(
        CourseTaskOption,
        on_delete=models.CASCADE,
        related_name="selected_in_answers",
        verbose_name="Выбранный вариант",
    )

    class Meta:
        verbose_name = "Выбранный вариант ответа"
        verbose_name_plural = "Выбранные варианты ответа"
        constraints = [
            models.UniqueConstraint(
                fields=("answer", "option"),
                name="courses_user_task_answer_option_unique_answer_option",
            ),
        ]

    def __str__(self):
        return (
            f"UserTaskAnswerOption<{self.id}> "
            f"- answer={self.answer_id} option={self.option_id}"
        )

    def clean(self):
        super().clean()
        if self.answer.task_id != self.option.task_id:
            raise ValidationError(
                {
                    "option": (
                        "Выбранный вариант должен относиться к тому же заданию, "
                        "что и ответ пользователя."
                    )
                }
            )


class UserTaskAnswerFile(models.Model):
    answer = models.ForeignKey(
        UserTaskAnswer,
        on_delete=models.CASCADE,
        related_name="files",
        verbose_name="Ответ пользователя",
    )
    file = models.ForeignKey(
        UserFile,
        on_delete=models.CASCADE,
        related_name="course_task_answer_files",
        verbose_name="Файл",
    )
    file_name = models.TextField(
        blank=True,
        default="",
        verbose_name="Название файла",
    )
    file_size = models.PositiveBigIntegerField(
        default=0,
        verbose_name="Размер файла",
    )
    datetime_uploaded = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата загрузки",
    )

    class Meta:
        verbose_name = "Файл ответа пользователя"
        verbose_name_plural = "Файлы ответов пользователей"
        ordering = ("-datetime_uploaded", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("answer", "file"),
                name="courses_user_task_answer_file_unique_answer_file",
            ),
        ]

    def __str__(self):
        return f"UserTaskAnswerFile<{self.id}> - answer={self.answer_id}"

    def save(self, *args, **kwargs):
        if self.file_id:
            if not self.file_name:
                self.file_name = self.file.name
            if self.file_size == 0:
                self.file_size = self.file.size
        super().save(*args, **kwargs)

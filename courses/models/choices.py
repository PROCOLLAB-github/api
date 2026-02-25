from django.db import models


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

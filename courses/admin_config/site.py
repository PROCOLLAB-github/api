from types import MethodType

from django.contrib import admin

from courses.models import (
    CourseLesson,
    CourseModule,
    CourseTask,
    CourseTaskOption,
    UserCourseProgress,
    UserLessonProgress,
    UserModuleProgress,
    UserTaskAnswer,
    UserTaskAnswerFile,
    UserTaskAnswerOption,
)

CourseModule._meta.verbose_name = "Модуль"
CourseModule._meta.verbose_name_plural = "Модули"
CourseLesson._meta.verbose_name = "Урок"
CourseLesson._meta.verbose_name_plural = "Уроки"
CourseTask._meta.verbose_name = "Задание"
CourseTask._meta.verbose_name_plural = "Задания"
CourseTaskOption._meta.verbose_name = "Вариант ответа"
CourseTaskOption._meta.verbose_name_plural = "Варианты ответов"
UserTaskAnswer._meta.verbose_name = "Ответ пользователя"
UserTaskAnswer._meta.verbose_name_plural = "Ответы пользователя"
UserTaskAnswerOption._meta.verbose_name = "Выбранный вариант"
UserTaskAnswerOption._meta.verbose_name_plural = "Выбранные варианты"
UserTaskAnswerFile._meta.verbose_name = "Файл"
UserTaskAnswerFile._meta.verbose_name_plural = "Файлы"
UserCourseProgress._meta.verbose_name = "Прогресс курса"
UserCourseProgress._meta.verbose_name_plural = "Прогресс курсов"
UserModuleProgress._meta.verbose_name = "Прогресс модуля"
UserModuleProgress._meta.verbose_name_plural = "Прогресс модулей"
UserLessonProgress._meta.verbose_name = "Прогресс урока"
UserLessonProgress._meta.verbose_name_plural = "Прогресс уроков"

COURSES_MODEL_ORDER = {
    "Course": 1,
    "CourseModule": 2,
    "CourseLesson": 3,
    "CourseTask": 4,
    "CourseTaskOption": 5,
    "UserTaskAnswer": 6,
    "UserTaskAnswerOption": 7,
    "UserTaskAnswerFile": 8,
    "UserCourseProgress": 9,
    "UserModuleProgress": 10,
    "UserLessonProgress": 11,
}


def courses_get_app_list(self, request, app_label=None):
    app_list = self._courses_original_get_app_list(request, app_label)
    for app in app_list:
        if app.get("app_label") == "courses":
            app["models"].sort(
                key=lambda model_info: COURSES_MODEL_ORDER.get(
                    model_info.get("object_name"),
                    999,
                )
            )
    return app_list


if not getattr(admin.site, "_courses_order_patched", False):
    admin.site._courses_original_get_app_list = admin.site.get_app_list
    admin.site.get_app_list = MethodType(courses_get_app_list, admin.site)
    admin.site._courses_order_patched = True

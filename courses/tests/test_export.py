from io import BytesIO

from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from courses.services.answers import TaskAnswerSubmitPayload, submit_user_task_answer
from courses.services.progress import recalculate_user_progresses_for_lesson

from .helpers import (
    create_choice_question_task,
    create_course,
    create_files_question_task,
    create_informational_task,
    create_lesson,
    create_module,
    create_staff_user,
    create_text_and_files_question_task,
    create_text_question_task,
    create_user,
    create_user_file,
)


class CourseResultsExportTests(TestCase):
    def setUp(self):
        self.admin_user = create_staff_user()
        self.client = Client()
        self.client.force_login(self.admin_user)

    def _read_workbook_rows(self, response):
        workbook = load_workbook(filename=BytesIO(response.content), read_only=True)
        worksheet = workbook[workbook.sheetnames[0]]
        return list(worksheet.iter_rows(values_only=True))

    def test_course_admin_export_contains_dynamic_task_columns_and_answers(self):
        course = create_course(title="Экспорт SQL")
        module = create_module(course, title="SQL basics", order=1)
        lesson = create_lesson(module, title="SELECT", order=1)
        student = create_user(prefix="export-student")
        create_user(prefix="export-not-started")

        info_task = create_informational_task(lesson, title="Введение", order=1)
        text_task = create_text_question_task(lesson, title="Опишите юнит-экономику", order=2)
        choice_task, options = create_choice_question_task(
            lesson,
            title="Какие метрики важны",
            order=3,
            answer_type="multiple_choice",
            options=[
                ("Retention", True),
                ("LTV", True),
                ("Bounce Rate", False),
            ],
        )
        spreadsheet = create_user_file(
            student,
            name="economics-model",
            extension="xlsx",
            mime_type=(
                "application/"
                "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        files_task = create_files_question_task(
            lesson,
            attachment_file=spreadsheet,
            title="Приложите расчёт",
            order=4,
        )
        create_text_and_files_question_task(
            lesson,
            title="Финальный вывод",
            order=5,
        )

        submit_user_task_answer(student, info_task, TaskAnswerSubmitPayload())
        recalculate_user_progresses_for_lesson(student, lesson)
        submit_user_task_answer(
            student,
            text_task,
            TaskAnswerSubmitPayload(answer_text="Указал юнит-экономику."),
        )
        recalculate_user_progresses_for_lesson(student, lesson)
        submit_user_task_answer(
            student,
            choice_task,
            TaskAnswerSubmitPayload(option_ids=[options[0].id, options[1].id]),
        )
        recalculate_user_progresses_for_lesson(student, lesson)
        submit_user_task_answer(
            student,
            files_task,
            TaskAnswerSubmitPayload(file_ids=[spreadsheet.pk]),
        )
        recalculate_user_progresses_for_lesson(student, lesson)

        response = self.client.get(
            reverse("admin:courses_export_results", args=[course.id])
        )
        rows = self._read_workbook_rows(response)

        self.assertEqual(response.status_code, 200)
        self.assertIn(".xlsx", response["Content-Disposition"])
        self.assertEqual(len(rows), 2)

        header = rows[0]
        data_row = rows[1]

        self.assertEqual(
            header[:6],
            (
                "Имя и Фамилия",
                "Email",
                "Прогресс курса, %",
                "Дата начала прохождения",
                "Название курса",
                "Текущий этап",
            ),
        )
        self.assertNotIn("Введение", "\n".join(str(value) for value in header))
        self.assertIn(
            "Модуль 1: SQL basics / Урок 1: SELECT / Задание 2: Опишите юнит-экономику",
            header,
        )
        self.assertIn(
            "Модуль 1: SQL basics / Урок 1: SELECT / Задание 5: Финальный вывод",
            header,
        )

        self.assertEqual(data_row[0], f"{student.first_name} {student.last_name}")
        self.assertEqual(data_row[1], student.email)
        self.assertEqual(data_row[2], 80)
        self.assertEqual(data_row[4], course.title)
        self.assertEqual(
            data_row[6:10],
            (
                "Указал юнит-экономику.",
                "Retention\nLTV",
                spreadsheet.link,
                None,
            ),
        )
        self.assertEqual(
            data_row[5],
            "Модуль 1: SQL basics / Урок 1: SELECT / Задание 5: Финальный вывод",
        )

    def test_course_admin_export_marks_completed_course_stage(self):
        course = create_course(title="Экспорт аналитики")
        module = create_module(course, title="Метрики", order=1)
        lesson = create_lesson(module, title="Базовые метрики", order=1)
        student = create_user(prefix="export-completed")
        task = create_text_question_task(
            lesson,
            title="Что такое retention",
            order=1,
        )

        submit_user_task_answer(
            student,
            task,
            TaskAnswerSubmitPayload(answer_text="Retention отражает возврат пользователей."),
        )
        recalculate_user_progresses_for_lesson(student, lesson)

        response = self.client.get(
            reverse("admin:courses_export_results", args=[course.id])
        )
        rows = self._read_workbook_rows(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][2], 100)
        self.assertEqual(rows[1][5], "Курс завершён")
        self.assertEqual(rows[1][6], "Retention отражает возврат пользователей.")

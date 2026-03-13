from datetime import date, timedelta

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import (
    create_choice_question_task,
    create_course,
    create_files_question_task,
    create_informational_task,
    create_lesson,
    create_module,
    create_text_and_files_question_task,
    create_text_question_task,
    create_user,
    create_user_file,
)


class CoursesExtendedAPITests(TestCase):
    def setUp(self):
        settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
        self.user = create_user(prefix="courses-extended")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_partial_progress_updates_after_info_wrong_and_correct_single_choice(self):
        course = create_course(title="SQL manual path")
        module_1 = create_module(
            course,
            title="SQL basics",
            order=1,
            start_date_value=date.today() - timedelta(days=1),
        )
        module_2 = create_module(
            course,
            title="SQL joins",
            order=2,
            start_date_value=date.today() + timedelta(days=7),
        )
        lesson_1 = create_lesson(module_1, title="SELECT", order=1)
        lesson_2 = create_lesson(module_1, title="WHERE", order=2)
        lesson_3 = create_lesson(module_2, title="LEFT JOIN", order=1)

        info_task = create_informational_task(lesson_1, title="Intro", order=1)
        choice_task, options = create_choice_question_task(
            lesson_1,
            title="Limit operator",
            order=2,
            answer_type="single_choice",
            options=[
                ("LIMIT", True),
                ("GROUP BY", False),
                ("HAVING", False),
            ],
        )
        create_informational_task(lesson_2, title="Sort intro", order=1)
        create_text_question_task(lesson_2, title="Filter example", order=2)
        create_informational_task(lesson_3, title="Join intro", order=1)

        structure_before = self.client.get(f"/courses/{course.id}/structure/").json()
        blocked_lesson_response = self.client.get(f"/courses/lessons/{lesson_2.id}/")

        self.assertEqual(structure_before["percent"], 0)
        self.assertFalse(structure_before["modules"][0]["lessons"][1]["is_available"])
        self.assertFalse(structure_before["modules"][1]["is_available"])
        self.assertEqual(
            structure_before["modules"][1]["start_date"],
            str(module_2.start_date),
        )
        self.assertEqual(blocked_lesson_response.status_code, 403)

        info_submit = self.client.post(
            f"/courses/tasks/{info_task.id}/answer/",
            {},
            format="json",
        )
        structure_after_info = self.client.get(f"/courses/{course.id}/structure/").json()

        self.assertEqual(info_submit.status_code, 200)
        self.assertEqual(
            structure_after_info["modules"][0]["lessons"][0]["percent"],
            50,
        )
        self.assertEqual(structure_after_info["modules"][0]["percent"], 25)
        self.assertEqual(structure_after_info["percent"], 16)

        duplicate_response = self.client.post(
            f"/courses/tasks/{choice_task.id}/answer/",
            {"option_ids": [options[0].id, options[0].id]},
            format="json",
        )
        wrong_response = self.client.post(
            f"/courses/tasks/{choice_task.id}/answer/",
            {"option_ids": [options[1].id]},
            format="json",
        )
        structure_after_wrong = self.client.get(f"/courses/{course.id}/structure/").json()

        self.assertEqual(duplicate_response.status_code, 400)
        self.assertEqual(wrong_response.status_code, 200)
        self.assertFalse(wrong_response.json()["is_correct"])
        self.assertFalse(wrong_response.json()["can_continue"])
        self.assertEqual(
            structure_after_wrong["modules"][0]["lessons"][0]["percent"],
            50,
        )
        self.assertEqual(structure_after_wrong["modules"][0]["percent"], 25)
        self.assertEqual(structure_after_wrong["percent"], 16)

        correct_response = self.client.post(
            f"/courses/tasks/{choice_task.id}/answer/",
            {"option_ids": [options[0].id]},
            format="json",
        )
        structure_after_correct = self.client.get(
            f"/courses/{course.id}/structure/"
        ).json()
        course_list = self.client.get("/courses/").json()
        course_card = next(item for item in course_list if item["id"] == course.id)
        resubmit_response = self.client.post(
            f"/courses/tasks/{info_task.id}/answer/",
            {},
            format="json",
        )

        self.assertEqual(correct_response.status_code, 200)
        self.assertTrue(correct_response.json()["is_correct"])
        self.assertTrue(correct_response.json()["can_continue"])
        self.assertEqual(
            structure_after_correct["modules"][0]["lessons"][0]["percent"],
            100,
        )
        self.assertEqual(
            structure_after_correct["modules"][0]["lessons"][1]["is_available"],
            True,
        )
        self.assertEqual(structure_after_correct["modules"][0]["percent"], 50)
        self.assertEqual(structure_after_correct["percent"], 33)
        self.assertEqual(course_card["action_state"], "continue")
        self.assertEqual(resubmit_response.status_code, 403)

    def test_files_and_text_and_files_flow_validates_payload_and_completes_course(self):
        course = create_course(title="Finance file path")
        module = create_module(course, title="Budgeting", order=1)
        lesson = create_lesson(module, title="Quarter plan", order=1)
        template_file = create_user_file(
            self.user,
            name="budget-template",
            extension="xlsx",
            mime_type=(
                "application/"
                "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        answer_file_1 = create_user_file(
            self.user,
            name="quarter-model",
            extension="xlsx",
            mime_type=(
                "application/"
                "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        answer_file_2 = create_user_file(
            self.user,
            name="board-deck",
            extension="pptx",
            mime_type=(
                "application/"
                "vnd.openxmlformats-officedocument.presentationml.presentation"
            ),
        )

        files_task = create_files_question_task(
            lesson,
            attachment_file=template_file,
            title="Upload template",
            order=1,
        )
        text_and_files_task = create_text_and_files_question_task(
            lesson,
            title="Explain risks",
            order=2,
        )
        files_task.answer_title = "Загрузите файл с расчётами"
        files_task.save(update_fields=["answer_title"])
        text_and_files_task.answer_title = "Добавьте комментарий и приложите материалы"
        text_and_files_task.save(update_fields=["answer_title"])

        invalid_file_response = self.client.post(
            f"/courses/tasks/{files_task.id}/answer/",
            {"file_ids": ["https://cdn.example.com/missing/file.pdf"]},
            format="json",
        )
        files_response = self.client.post(
            f"/courses/tasks/{files_task.id}/answer/",
            {"file_ids": [answer_file_1.pk]},
            format="json",
        )
        invalid_text_and_files_response = self.client.post(
            f"/courses/tasks/{text_and_files_task.id}/answer/",
            {"answer_text": "Риск кассового разрыва."},
            format="json",
        )
        valid_text_and_files_response = self.client.post(
            f"/courses/tasks/{text_and_files_task.id}/answer/",
            {
                "answer_text": "Риски: кассовый разрыв и рост fixed costs.",
                "file_ids": [answer_file_1.pk, answer_file_2.pk],
            },
            format="json",
        )
        lesson_detail = self.client.get(f"/courses/lessons/{lesson.id}/").json()
        course_detail = self.client.get(f"/courses/{course.id}/").json()

        self.assertEqual(invalid_file_response.status_code, 400)
        self.assertEqual(files_response.status_code, 200)
        self.assertTrue(files_response.json()["can_continue"])
        self.assertEqual(invalid_text_and_files_response.status_code, 400)
        self.assertEqual(valid_text_and_files_response.status_code, 200)
        self.assertEqual(lesson_detail["module_order"], 1)
        self.assertEqual(
            lesson_detail["tasks"][0]["answer_title"],
            "Загрузите файл с расчётами",
        )
        self.assertEqual(
            lesson_detail["tasks"][1]["answer_title"],
            "Добавьте комментарий и приложите материалы",
        )
        self.assertEqual(course_detail["progress_status"], "completed")
        self.assertEqual(course_detail["percent"], 100)

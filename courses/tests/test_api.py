from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from .helpers import (
    add_program_member,
    create_course_tree,
    create_partner_program,
    create_user,
)


class CoursesAPITests(TestCase):
    def setUp(self):
        settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
        self.client = APIClient()
        self.user = create_user(prefix="api-user")
        self.client.force_authenticate(self.user)

    def test_public_course_flow_updates_progress_across_all_levels(self):
        course = create_course_tree(module_count=2, lesson_count=2, task_count=2)
        lesson = course.modules.get(order=1).lessons.get(order=1)
        info_task = lesson.tasks.get(order=1)
        question_task = lesson.tasks.get(order=2)

        lesson_before = self.client.get(f"/courses/lessons/{lesson.id}/")
        info_submit = self.client.post(
            f"/courses/tasks/{info_task.id}/answer/",
            {},
            format="json",
        )
        structure_after_info = self.client.get(f"/courses/{course.id}/structure/")
        question_submit = self.client.post(
            f"/courses/tasks/{question_task.id}/answer/",
            {"answer_text": "ok"},
            format="json",
        )
        course_detail_after_question = self.client.get(f"/courses/{course.id}/")

        self.assertEqual(lesson_before.status_code, 200)
        self.assertFalse(lesson_before.json()["tasks"][0]["is_completed"])
        self.assertEqual(info_submit.status_code, 200)
        self.assertTrue(info_submit.json()["can_continue"])
        self.assertEqual(
            structure_after_info.json()["modules"][0]["lessons"][0]["percent"],
            50,
        )
        self.assertEqual(question_submit.status_code, 200)
        self.assertEqual(course_detail_after_question.json()["percent"], 25)
        self.assertEqual(
            course_detail_after_question.json()["progress_status"],
            "in_progress",
        )

    def test_program_member_access_and_visit_restriction(self):
        program = create_partner_program()
        member_user = create_user(prefix="member")
        outsider_user = create_user(prefix="outsider")
        add_program_member(program, member_user)
        course = create_course_tree(
            access_type="program_members",
            partner_program=program,
        )
        lesson = course.modules.get(order=1).lessons.get(order=1)

        member_client = APIClient()
        member_client.force_authenticate(member_user)
        outsider_client = APIClient()
        outsider_client.force_authenticate(outsider_user)

        member_response = member_client.get(f"/courses/lessons/{lesson.id}/")
        outsider_response = outsider_client.get(f"/courses/lessons/{lesson.id}/")
        outsider_visit_response = outsider_client.post(
            f"/courses/{course.id}/visit/",
            {},
            format="json",
        )

        self.assertEqual(member_response.status_code, 200)
        self.assertEqual(outsider_response.status_code, 403)
        self.assertEqual(outsider_visit_response.status_code, 403)

    def test_unauthorized_courses_list_returns_401(self):
        client = APIClient()

        response = client.get("/courses/")

        self.assertEqual(response.status_code, 401)

from django.test import TestCase
from rest_framework.test import APIClient

from courses.models import CourseAccessType, CourseContentStatus
from partner_programs.tests.helpers import (
    create_course,
    create_partner_program,
    create_program_member,
    create_user,
)


class PartnerProgramDetailCoursesTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_detail_includes_related_courses_with_availability_for_member(self):
        program = create_partner_program(name="Program with courses")
        member = create_user(prefix="member-program")
        create_program_member(program, user=member)
        all_users_course = create_course(
            program,
            title="Open course",
            access_type=CourseAccessType.ALL_USERS,
        )
        member_course = create_course(
            program,
            title="Members course",
            access_type=CourseAccessType.PROGRAM_MEMBERS,
        )
        create_course(
            program,
            title="Draft course",
            access_type=CourseAccessType.ALL_USERS,
            status=CourseContentStatus.DRAFT,
        )
        self.client.force_authenticate(member)

        response = self.client.get(f"/programs/{program.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_user_member"])
        self.assertEqual(
            response.data["courses"],
            [
                {
                    "id": all_users_course.id,
                    "title": "Open course",
                    "is_available": True,
                },
                {
                    "id": member_course.id,
                    "title": "Members course",
                    "is_available": True,
                },
            ],
        )

    def test_detail_includes_empty_courses_list_when_program_has_no_related_courses(self):
        program = create_partner_program()
        user = create_user(prefix="plain-program-user")
        self.client.force_authenticate(user)

        response = self.client.get(f"/programs/{program.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["courses"], [])

    def test_detail_marks_program_only_courses_as_unavailable_for_non_member(self):
        program = create_partner_program()
        outsider = create_user(prefix="outsider-program")
        open_course = create_course(
            program,
            title="Open course",
            access_type=CourseAccessType.ALL_USERS,
        )
        member_course = create_course(
            program,
            title="Members course",
            access_type=CourseAccessType.PROGRAM_MEMBERS,
        )
        self.client.force_authenticate(outsider)

        response = self.client.get(f"/programs/{program.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_user_member"])
        self.assertEqual(
            response.data["courses"],
            [
                {
                    "id": open_course.id,
                    "title": "Open course",
                    "is_available": True,
                },
                {
                    "id": member_course.id,
                    "title": "Members course",
                    "is_available": False,
                },
            ],
        )

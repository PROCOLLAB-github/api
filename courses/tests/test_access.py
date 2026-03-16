from django.test import TestCase

from courses.models import CourseAccessType
from courses.services.access import resolve_course_availability

from .helpers import add_program_member, create_course, create_partner_program, create_user


class CourseAccessServiceTests(TestCase):
    def test_all_users_course_available_for_authenticated_user(self):
        user = create_user()
        course = create_course(access_type=CourseAccessType.ALL_USERS)

        availability = resolve_course_availability(course, user)

        self.assertTrue(availability.is_available)

    def test_program_members_course_blocked_for_outsider(self):
        user = create_user(prefix="outsider")
        program = create_partner_program()
        course = create_course(
            access_type=CourseAccessType.PROGRAM_MEMBERS,
            partner_program=program,
        )

        availability = resolve_course_availability(course, user)

        self.assertFalse(availability.is_available)
        self.assertEqual(availability.reason, "not_program_member")

    def test_program_members_course_available_for_member(self):
        user = create_user(prefix="member")
        program = create_partner_program()
        add_program_member(program, user)
        course = create_course(
            access_type=CourseAccessType.PROGRAM_MEMBERS,
            partner_program=program,
        )

        availability = resolve_course_availability(course, user)

        self.assertTrue(availability.is_available)

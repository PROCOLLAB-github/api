from django.test import TestCase
from rest_framework.test import APIClient

from courses.models import CourseAccessType, CourseContentStatus
from projects.models import Collaborator
from partner_programs.tests.helpers import (
    create_course,
    create_partner_program,
    create_program_member,
    create_program_project,
    create_project,
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


class PartnerProgramCurrentApplicationDetailTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def get_detail(self, program):
        return self.client.get(f"/programs/{program.id}/")

    def test_anonymous_user_has_no_current_application(self):
        program = create_partner_program()

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["current_application"])

    def test_authenticated_non_member_has_no_current_application(self):
        program = create_partner_program()
        user = create_user(prefix="non-member-application")
        project = create_project(leader=user)
        create_program_project(program, project=project)
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_user_member"])
        self.assertIsNone(response.data["current_application"])

    def test_member_without_application_has_no_current_application(self):
        program = create_partner_program()
        user = create_user(prefix="member-without-application")
        create_program_member(program, user=user)
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_user_member"])
        self.assertIsNone(response.data["current_application"])

    def test_member_receives_draft_current_application(self):
        program = create_partner_program()
        user = create_user(prefix="draft-application")
        create_program_member(program, user=user)
        project = create_project(leader=user, draft=True)
        link = create_program_project(program, project=project)
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["current_application"],
            {
                "project_id": project.id,
                "program_link_id": link.id,
                "submitted": False,
            },
        )

    def test_member_receives_submitted_state_from_program_link(self):
        program = create_partner_program()
        user = create_user(prefix="submitted-application")
        create_program_member(program, user=user)
        project = create_project(leader=user)
        link = create_program_project(program, project=project, submitted=True)
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["current_application"],
            {
                "project_id": project.id,
                "program_link_id": link.id,
                "submitted": True,
            },
        )

    def test_multi_program_project_returns_link_for_requested_program(self):
        program_a = create_partner_program(name="Program A")
        program_b = create_partner_program(name="Program B")
        user = create_user(prefix="multi-program-application")
        create_program_member(program_b, user=user)
        project = create_project(leader=user)
        create_program_project(program_a, project=project)
        link_b = create_program_project(program_b, project=project)
        self.client.force_authenticate(user)

        response = self.get_detail(program_b)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["current_application"]["project_id"], project.id)
        self.assertEqual(
            response.data["current_application"]["program_link_id"], link_b.id
        )

    def test_projects_from_other_programs_do_not_affect_application(self):
        program_a = create_partner_program(name="Independent Program A")
        program_b = create_partner_program(name="Independent Program B")
        user = create_user(prefix="independent-program-application")
        create_program_member(program_b, user=user)
        project_a = create_project(leader=user, name="Project A")
        project_b = create_project(leader=user, name="Project B")
        create_program_project(program_a, project=project_a)
        link_b = create_program_project(program_b, project=project_b)
        self.client.force_authenticate(user)

        response = self.get_detail(program_b)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["current_application"],
            {
                "project_id": project_b.id,
                "program_link_id": link_b.id,
                "submitted": False,
            },
        )

    def test_other_users_project_is_not_current_application(self):
        program = create_partner_program()
        user = create_user(prefix="application-viewer")
        other_user = create_user(prefix="other-application-leader")
        create_program_member(program, user=user)
        create_program_project(program, project=create_project(leader=other_user))
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["current_application"])

    def test_collaborator_project_is_not_current_application(self):
        program = create_partner_program()
        user = create_user(prefix="application-collaborator")
        leader = create_user(prefix="collaborator-project-leader")
        create_program_member(program, user=user)
        project = create_project(leader=leader)
        create_program_project(program, project=project)
        Collaborator.objects.create(user=user, project=project, role="Participant")
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["current_application"])

    def test_legacy_duplicate_uses_lowest_program_link_id(self):
        program = create_partner_program()
        user = create_user(prefix="duplicate-application")
        create_program_member(program, user=user)
        first_project = create_project(leader=user, name="First application")
        second_project = create_project(leader=user, name="Second application")
        first_link = create_program_project(program, project=first_project)
        create_program_project(program, project=second_project)
        self.client.force_authenticate(user)

        response = self.get_detail(program)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["current_application"],
            {
                "project_id": first_project.id,
                "program_link_id": first_link.id,
                "submitted": False,
            },
        )

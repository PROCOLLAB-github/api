from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from courses.models import (
    CourseAccessType,
    CourseContentStatus,
    CourseLessonContentStatus,
    CourseModuleContentStatus,
    ProgressStatus,
)
from courses.services.access import (
    ACTION_CONTINUE,
    ACTION_LOCK,
    ACTION_START,
    is_course_completed,
    is_lesson_available,
    is_module_available,
    is_user_program_member,
    moscow_today,
    resolve_course_action_state,
    resolve_course_availability,
    resolve_course_card_state,
    resolve_course_date_label,
)

from .helpers import (
    add_program_member,
    create_course,
    create_lesson,
    create_module,
    create_partner_program,
    create_user,
)


class CourseAccessServiceTests(TestCase):
    def assert_course_unavailable(self, course, user, reason):
        availability = resolve_course_availability(course, user)

        self.assertFalse(availability.is_available)
        self.assertEqual(availability.reason, reason)

    def test_moscow_today_accepts_naive_datetime(self):
        self.assertEqual(
            moscow_today(datetime(2026, 5, 12, 12, 0)),
            date(2026, 5, 12),
        )

    def test_course_completed_by_status(self):
        course = create_course()
        course.status = CourseContentStatus.COMPLETED
        course.is_completed = True

        self.assertTrue(is_course_completed(course, today=date(2026, 5, 12)))

    def test_course_completed_by_flag(self):
        course = create_course()
        course.is_completed = True

        self.assertTrue(is_course_completed(course, today=date(2026, 5, 12)))

    def test_course_completed_by_end_date(self):
        today = date(2026, 5, 12)
        course = create_course()
        course.start_date = today - timedelta(days=10)
        course.end_date = today - timedelta(days=1)

        self.assertTrue(is_course_completed(course, today=today))

    def test_all_users_course_available_for_authenticated_user(self):
        user = create_user()
        course = create_course(access_type=CourseAccessType.ALL_USERS)

        availability = resolve_course_availability(course, user)

        self.assertTrue(availability.is_available)

    def test_course_availability_blocks_unauthenticated_user(self):
        course = create_course()

        self.assert_course_unavailable(
            course,
            AnonymousUser(),
            "authentication_required",
        )

    def test_course_availability_blocks_draft_course(self):
        user = create_user()
        course = create_course(status=CourseContentStatus.DRAFT)

        self.assert_course_unavailable(course, user, "draft")

    def test_course_availability_blocks_completed_course(self):
        user = create_user()
        course = create_course()
        course.status = CourseContentStatus.COMPLETED
        course.is_completed = True

        self.assert_course_unavailable(course, user, "completed")

    def test_course_availability_blocks_subscription_stub(self):
        user = create_user()
        course = create_course(access_type=CourseAccessType.SUBSCRIPTION_STUB)

        self.assert_course_unavailable(course, user, "subscription_required")

    def test_program_members_course_blocked_for_outsider(self):
        user = create_user(prefix="outsider")
        program = create_partner_program()
        course = create_course(
            access_type=CourseAccessType.PROGRAM_MEMBERS,
            partner_program=program,
        )

        self.assert_course_unavailable(course, user, "not_program_member")

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

    def test_is_user_program_member_handles_anonymous_user_and_course_without_program(self):
        user = create_user()
        course = create_course()

        self.assertFalse(is_user_program_member(course, AnonymousUser()))
        self.assertFalse(is_user_program_member(course, user))

    def test_course_action_state_starts_without_progress(self):
        user = create_user()
        course = create_course()

        self.assertEqual(resolve_course_action_state(course, user), ACTION_START)

    def test_course_action_state_starts_for_not_started_progress(self):
        user = create_user()
        course = create_course()

        action_state = resolve_course_action_state(
            course,
            user,
            progress=SimpleNamespace(status=ProgressStatus.NOT_STARTED),
        )

        self.assertEqual(action_state, ACTION_START)

    def test_course_action_state_continues_for_in_progress(self):
        user = create_user()
        course = create_course()

        action_state = resolve_course_action_state(
            course,
            user,
            progress=SimpleNamespace(status=ProgressStatus.IN_PROGRESS),
        )

        self.assertEqual(action_state, ACTION_CONTINUE)

    def test_course_action_state_locks_completed_progress(self):
        user = create_user()
        course = create_course()

        action_state = resolve_course_action_state(
            course,
            user,
            progress=SimpleNamespace(status=ProgressStatus.COMPLETED),
        )

        self.assertEqual(action_state, ACTION_LOCK)

    def test_course_action_state_locks_unavailable_course(self):
        course = create_course()

        self.assertEqual(
            resolve_course_action_state(course, AnonymousUser()),
            ACTION_LOCK,
        )

    def test_course_date_label_for_indefinite_course(self):
        course = create_course()

        self.assertEqual(
            resolve_course_date_label(course, today=date(2026, 5, 12)),
            "бессрочно",
        )

    def test_course_date_label_for_future_course(self):
        today = date(2026, 5, 12)
        course = create_course()
        course.start_date = today + timedelta(days=1)
        course.end_date = today + timedelta(days=10)

        self.assertEqual(
            resolve_course_date_label(course, today=today),
            "13.05.26 - 22.05.26",
        )

    def test_course_date_label_for_active_course(self):
        today = date(2026, 5, 12)
        course = create_course()
        course.start_date = today - timedelta(days=1)
        course.end_date = today + timedelta(days=10)

        self.assertEqual(
            resolve_course_date_label(course, today=today),
            "доступен до 22.05.2026",
        )

    def test_course_date_label_for_completed_course(self):
        course = create_course()
        course.status = CourseContentStatus.COMPLETED
        course.is_completed = True

        self.assertEqual(
            resolve_course_date_label(course, today=date(2026, 5, 12)),
            "курс завершен",
        )

    def test_course_card_state_combines_availability_action_and_date_label(self):
        user = create_user()
        course = create_course()

        state = resolve_course_card_state(course, user)

        self.assertTrue(state.is_available)
        self.assertEqual(state.action_state, ACTION_START)
        self.assertEqual(state.date_label, "бессрочно")

    def test_module_available_for_available_course_published_module_and_completed_previous(self):
        course = create_course()
        module = create_module(course)

        self.assertTrue(
            is_module_available(
                module,
                course_available=True,
                previous_module_completed=True,
                today=date(2026, 5, 12),
            )
        )

    def test_module_unavailable_when_course_is_unavailable(self):
        course = create_course()
        module = create_module(course)

        self.assertFalse(
            is_module_available(
                module,
                course_available=False,
                previous_module_completed=True,
                today=date(2026, 5, 12),
            )
        )

    def test_module_unavailable_when_module_is_draft(self):
        course = create_course()
        module = create_module(course, status=CourseModuleContentStatus.DRAFT)

        self.assertFalse(
            is_module_available(
                module,
                course_available=True,
                previous_module_completed=True,
                today=date(2026, 5, 12),
            )
        )

    def test_module_unavailable_before_start_date(self):
        today = date(2026, 5, 12)
        course = create_course()
        module = create_module(course, start_date_value=today + timedelta(days=1))

        self.assertFalse(
            is_module_available(
                module,
                course_available=True,
                previous_module_completed=True,
                today=today,
            )
        )

    def test_module_unavailable_when_previous_module_is_not_completed(self):
        course = create_course()
        module = create_module(course)

        self.assertFalse(
            is_module_available(
                module,
                course_available=True,
                previous_module_completed=False,
                today=date(2026, 5, 12),
            )
        )

    def test_lesson_available_for_available_module_published_lesson_and_completed_previous(self):
        course = create_course()
        module = create_module(course)
        lesson = create_lesson(module)

        self.assertTrue(
            is_lesson_available(
                lesson,
                module_available=True,
                previous_lesson_completed=True,
            )
        )

    def test_lesson_unavailable_when_module_is_unavailable(self):
        course = create_course()
        module = create_module(course)
        lesson = create_lesson(module)

        self.assertFalse(
            is_lesson_available(
                lesson,
                module_available=False,
                previous_lesson_completed=True,
            )
        )

    def test_lesson_unavailable_when_lesson_is_draft(self):
        course = create_course()
        module = create_module(course)
        lesson = create_lesson(module, status=CourseLessonContentStatus.DRAFT)

        self.assertFalse(
            is_lesson_available(
                lesson,
                module_available=True,
                previous_lesson_completed=True,
            )
        )

    def test_lesson_unavailable_when_previous_lesson_is_not_completed(self):
        course = create_course()
        module = create_module(course)
        lesson = create_lesson(module)

        self.assertFalse(
            is_lesson_available(
                lesson,
                module_available=True,
                previous_lesson_completed=False,
            )
        )

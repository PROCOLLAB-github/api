from unittest import skipIf, skipUnless

from django.conf import settings
from django.contrib import admin
from django.test import SimpleTestCase, TestCase
from django.urls import Resolver404, resolve

from partner_programs.models import (
    Application,
    Evaluation,
    EvaluationAmendment,
    EvaluationScore,
    Submission,
    SubmissionExpertAssignment,
    Team,
    TeamInvite,
    TeamMember,
)
from partner_programs.tests.helpers import create_user


NEXTGEN_MODELS = (
    Application,
    Team,
    TeamMember,
    TeamInvite,
    Submission,
    SubmissionExpertAssignment,
    Evaluation,
    EvaluationScore,
    EvaluationAmendment,
)

NEXTGEN_URLS = (
    "/applications/1/",
    "/submissions/1/",
    "/evaluations/1/",
    "/expert/submissions/",
    "/submission-assignments/1/revoke/",
    "/team-invites/my/",
    "/programs/managed/",
    "/programs/1/manager-overview/",
    "/programs/1/evaluations/",
    "/programs/1/submission-assignments/",
    "/programs/1/applications/",
    "/programs/1/applications/my/",
    "/projects/catalog/",
    "/projects/my/",
    "/projects/subscribed/",
    "/projects/workspace/",
    "/projects/workspace/invitations/incoming/",
    "/projects/workspace/invitations/1/accept/",
    "/projects/workspace/invitations/1/decline/",
    "/projects/1/workspace/",
    "/projects/1/workspace/invitations/",
    "/projects/1/workspace/invitations/candidates/",
    "/projects/1/workspace/invitations/1/revoke/",
    "/projects/1/workspace/subscription/",
    "/projects/1/workspace/goals/",
    "/projects/1/workspace/goals/1/",
    "/projects/1/workspace/achievements/",
    "/projects/1/workspace/achievements/1/",
    "/feed/news/",
    "/feed/news/1/",
    "/feed/news/1/set-liked/",
    "/feed/news/1/set-viewed/",
    "/feed/news/1/comments/",
    "/feed/news/1/comments/1/",
    "/auth/profiles/",
    "/auth/profiles/1/",
)

LEGACY_URLS = (
    "/programs/",
    "/programs/1/",
    "/programs/1/project-analytics/",
    "/programs/1/project-analytics/assignments/",
    "/programs/1/project-analytics/assignments/1/scores/",
    "/programs/partner-program-projects/1/fields/",
    "/programs/partner-program-projects/1/submit/",
    "/programs/1/projects/",
    "/programs/1/projects/filter/",
    "/programs/1/projects/apply/",
    "/programs/1/filters/",
    "/programs/1/news/",
    "/projects/1/",
    "/projects/1/news/",
    "/projects/1/collaborators/",
    "/invites/",
    "/invites/1/accept/",
    "/vacancies/",
    "/vacancies/1/responses/",
    "/rate-project/1",
    "/rate-project/rate/1",
    "/courses/",
    "/chats/directs/",
    "/feed/",
    "/auth/users/current/",
    "/auth/users/1/news/",
    "/notifications/",
    "/notifications/unread-count/",
    "/notifications/read-all/",
    "/notifications/1/read/",
)


@skipIf(
    settings.NEXTGEN_SURFACE_ENABLED,
    "Feature-off contract runs in a process with NEXTGEN_SURFACE_ENABLED=False.",
)
class NextgenSurfaceDisabledTests(TestCase):
    def test_nextgen_routes_do_not_resolve_and_return_404(self):
        for url in NEXTGEN_URLS:
            with self.subTest(url=url):
                with self.assertRaises(Resolver404):
                    resolve(url)
                self.assertEqual(self.client.get(url, secure=True).status_code, 404)

    def test_legacy_and_notification_routes_still_resolve(self):
        for url in LEGACY_URLS:
            with self.subTest(url=url):
                self.assertIsNotNone(resolve(url))

    def test_nextgen_models_are_not_registered_in_admin(self):
        self.client.force_login(
            create_user(is_staff=True, is_superuser=True, is_active=True)
        )

        for model in NEXTGEN_MODELS:
            with self.subTest(model=model.__name__):
                self.assertNotIn(model, admin.site._registry)
                response = self.client.get(
                    f"/admin/{model._meta.app_label}/{model._meta.model_name}/"
                )
                self.assertEqual(response.status_code, 404)


@skipUnless(
    settings.NEXTGEN_SURFACE_ENABLED,
    "Feature-on contract runs in a process with NEXTGEN_SURFACE_ENABLED=True.",
)
class NextgenSurfaceEnabledTests(SimpleTestCase):
    def test_nextgen_routes_resolve(self):
        for url in NEXTGEN_URLS:
            with self.subTest(url=url):
                self.assertIsNotNone(resolve(url))

    def test_nextgen_models_are_registered_in_admin(self):
        for model in NEXTGEN_MODELS:
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)

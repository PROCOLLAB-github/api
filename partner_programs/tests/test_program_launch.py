from uuid import uuid4
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import View
from partner_programs.models import (
    PartnerProgram,
    PartnerProgramUserProfile,
    ProgramRegistration,
)
from partner_programs.services.program_launch import publish_program
from partner_programs.tests.helpers import create_partner_program, create_user


class ProgramLaunchTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.creator = create_user(prefix="creator", is_active=True)
        self.permission = Permission.objects.get(
            content_type__app_label="partner_programs", codename="add_partnerprogram"
        )
        self.creator.user_permissions.add(self.permission)
        self.client.force_authenticate(self.creator)

    def create(self, **changes):
        data = dict(
            name="Новая программа",
            format="case_championship",
            idempotency_key=str(uuid4()),
        )
        data.update(changes)
        return self.client.post("/programs/drafts/", data, format="json")


class ProgramCreationTests(ProgramLaunchTestCase):
    def test_all_formats_start_private_without_fake_dates_and_enrollment(self):
        for kind in ("case_championship", "hackathon", "noncompetitive"):
            with self.subTest(kind=kind):
                response = self.create(format=kind)
                self.assertEqual(response.status_code, 201, response.data)
                program = PartnerProgram.objects.get(pk=response.data["id"])
                self.assertTrue(program.draft)
                self.assertTrue(program.managers.filter(pk=self.creator.pk).exists())
                self.assertFalse(program.users.exists())
                self.assertIsNone(program.datetime_started)
                self.assertIsNone(program.datetime_finished)
                self.assertIsNone(program.datetime_registration_ends)
                self.assertEqual(program.is_competitive, kind != "noncompetitive")
                self.assertEqual(
                    program.solution_creation_enabled, kind != "noncompetitive"
                )

    def test_staff_and_existing_manager_need_explicit_creation_permission(self):
        for staff in (False, True):
            user = create_user(is_staff=staff)
            create_partner_program().managers.add(user)
            self.client.force_authenticate(user)
            self.assertEqual(self.create().status_code, 403)
            self.assertEqual(
                self.client.get("/programs/capabilities/").data["can_create_program"],
                False,
            )
        self.assertFalse(PartnerProgram.objects.filter(created_by__isnull=False).exists())

    def test_anonymous_cannot_create(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.create().status_code, 401)

    def test_repeat_is_idempotent_even_after_name_is_edited(self):
        key = str(uuid4())
        response = self.create(idempotency_key=key)
        program = PartnerProgram.objects.get(pk=response.data["id"])
        program.name = "Новое название"
        program.save(update_fields=["name", "datetime_updated"])
        retry = self.create(idempotency_key=key)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.data["id"], program.pk)
        self.assertEqual(
            PartnerProgram.objects.filter(created_by=self.creator).count(), 1
        )
        self.assertEqual(
            self.create(idempotency_key=key, format="hackathon").status_code, 409
        )

    def test_scope_pagination_search_and_revoked_creation_right(self):
        mine = self.create().data["id"]
        other = create_partner_program(name="Чужая программа", draft=True)
        self.creator.user_permissions.remove(self.permission)
        self.creator = type(self.creator).objects.get(pk=self.creator.pk)
        self.client.force_authenticate(self.creator)
        self.assertEqual(self.create().status_code, 403)
        response = self.client.get("/programs/managed/?limit=1&offset=0&search=Новая")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([r["id"] for r in response.data["results"]], [mine])
        self.assertNotEqual(mine, other.pk)
        self.assertEqual(
            self.client.get(f"/programs/{mine}/management/").status_code, 200
        )

    def test_invalid_requests_do_not_leave_empty_programs(self):
        for data in (
            {"name": "  "},
            {"format": "other"},
            {"idempotency_key": "bad"},
            {"draft": False},
        ):
            self.assertEqual(self.create(**data).status_code, 400)
        self.assertFalse(PartnerProgram.objects.exists())

    def test_legacy_catalog_post_cannot_bypass_permission(self):
        user = create_user()
        self.client.force_authenticate(user)
        self.assertEqual(
            self.client.post("/programs/", {"name": "Обход"}, format="json").status_code,
            403,
        )
        self.assertFalse(PartnerProgram.objects.exists())

    def test_draft_is_hidden_across_public_endpoints(self):
        pk = self.create().data["id"]
        stranger = create_user()
        for user in (None, stranger):
            self.client.force_authenticate(user)
            for suffix in (
                "",
                "schema/",
                "news/",
                "filters/",
                "projects/",
                "published-projects/",
                "published-solutions/",
                "registration/",
                "solution-context/",
                "solution-form/",
                "management/",
                "management/preview/",
            ):
                with self.subTest(user=user, suffix=suffix):
                    self.assertEqual(
                        self.client.get(f"/programs/{pk}/{suffix}").status_code, 404
                    )
            for suffix in (
                "register/",
                "register_new/",
                "set_viewed/",
                "set_liked/",
                "projects/apply/",
                "solutions/",
            ):
                with self.subTest(user=user, suffix=suffix):
                    self.assertEqual(
                        self.client.post(
                            f"/programs/{pk}/{suffix}", {}, format="json"
                        ).status_code,
                        404,
                    )
            ids = [row["id"] for row in self.client.get("/programs/").data["results"]]
            self.assertNotIn(pk, ids)

    def test_preview_has_no_enrollment_or_view_side_effects_and_disallows_mutations(self):
        pk = self.create().data["id"]
        before = View.objects.count()
        response = self.client.get(f"/programs/{pk}/management/preview/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["preview"])
        self.assertEqual(response.data["name"], "Новая программа")
        self.assertFalse(
            PartnerProgramUserProfile.objects.filter(partner_program_id=pk).exists()
        )
        self.assertEqual(View.objects.count(), before)
        self.assertEqual(
            self.client.post(
                f"/programs/{pk}/set_viewed/", {}, format="json"
            ).status_code,
            404,
        )

    def test_project_creation_cannot_bind_to_an_unpublished_program(self):
        pk = self.create().data["id"]
        response = self.client.post(
            "/projects/", {"name": "Обход", "partner_program_id": pk}, format="json"
        )
        self.assertEqual(response.status_code, 404, response.data)

    def test_new_program_manager_can_read_page_without_becoming_a_participant(self):
        program = PartnerProgram.objects.get(pk=self.create().data["id"])
        program.description = "Описание новой программы"
        program.save()
        response = self.client.get(f"/programs/{program.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["description"], program.description)
        self.assertTrue(response.data["is_user_manager"])
        self.assertFalse(response.data["is_user_member"])
        self.assertIsNone(response.data["welcome_acknowledged_at"])
        self.assertFalse(
            PartnerProgramUserProfile.objects.filter(partner_program=program).exists()
        )

    def test_personal_program_lists_do_not_reveal_drafts_even_with_a_profile(self):
        hidden = PartnerProgram.objects.get(pk=self.create().data["id"])
        published = create_partner_program(draft=False)
        participant = create_user()
        for program in (hidden, published):
            PartnerProgramUserProfile.objects.create(
                partner_program=program, user=participant, partner_program_data={}
            )
        self.client.force_authenticate(participant)
        for url in (
            "/auth/users/current/programs/",
            "/auth/users/current/programs/tags/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual([row["id"] for row in response.data], [published.pk])

    def test_draft_reads_and_hidden_responses_are_not_cacheable(self):
        pk = self.create().data["id"]
        response = self.client.get(f"/programs/{pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.client.force_authenticate(None)
        response = self.client.get(f"/programs/{pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Cache-Control"], "private, no-store")


class ProgramPublicationTests(ProgramLaunchTestCase):
    def setUp(self):
        super().setUp()
        self.program = PartnerProgram.objects.get(pk=self.create().data["id"])
        self.url = f"/programs/{self.program.pk}/management/"

    def configure(self, mode="native"):
        now = timezone.now()
        self.program.description = "Описание программы"
        self.program.datetime_started = now + timezone.timedelta(days=10)
        self.program.datetime_finished = now + timezone.timedelta(days=30)
        self.program.datetime_registration_ends = now + timezone.timedelta(days=5)
        self.program.save()
        return ProgramRegistration.objects.create(
            program=self.program, draft={"mode": mode, "fields": []}
        )

    def state(self):
        response = self.client.get(self.url + "launch/")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def publish(self, revision=None):
        return self.client.post(
            self.url + "publish/",
            {"revision": revision or self.state()["revision"]},
            format="json",
        )

    def test_blockers_explain_missing_settings_and_publish_does_not_partially_commit(
        self,
    ):
        state = self.state()
        self.assertEqual(
            {r["code"] for r in state["blockers"]}, {"page", "dates", "registration"}
        )
        self.assertFalse(state["can_publish"])
        self.assertEqual(self.publish().status_code, 400)
        self.program.refresh_from_db()
        self.assertTrue(self.program.draft)
        self.assertFalse(
            ProgramRegistration.objects.filter(program=self.program).exists()
        )

    def test_first_publication_opens_native_registration_without_solution_setup(self):
        config = self.configure()
        self.assertTrue(self.state()["can_publish"])
        response = self.publish()
        self.assertEqual(response.status_code, 200, response.data)
        self.program.refresh_from_db()
        config.refresh_from_db()
        self.assertFalse(self.program.draft)
        self.assertEqual(config.published, {"mode": "native", "fields": []})
        self.assertEqual(config.published_version, 1)
        self.assertEqual(
            self.client.get(f"/programs/{self.program.pk}/registration/").status_code, 200
        )
        self.assertIn(str(self.program.pk), response.data["links"]["registration"])
        self.assertFalse(self.program.fields.exists())

    def test_registration_preparation_does_not_publish_anything_while_program_is_draft(
        self,
    ):
        response = self.client.post(
            self.url + "registration/publish/",
            {"revision": 0, "draft": {"mode": "native", "fields": []}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["program_draft"])
        self.assertIsNone(response.data["published"])
        self.assertIsNone(response.data["link"])
        self.program.refresh_from_db()
        self.assertTrue(self.program.draft)

    def test_external_registration_waits_for_real_connection(self):
        config = self.configure("external")
        self.assertEqual([r["code"] for r in self.state()["blockers"]], ["registration"])
        self.assertEqual(self.publish().status_code, 400)
        config.external_status = "connected"
        config.external_url = "https://event.example.test/register"
        config.save()
        response = self.publish()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["links"]["registration"], config.external_url)

    def test_stale_settings_and_questionnaire_are_detected(self):
        config = self.configure()
        for change in ("program", "registration"):
            revision = self.state()["revision"]
            if change == "program":
                self.program.description += " Изменение"
                self.program.save()
            else:
                config.revision += 1
                config.save()
            response = self.publish(revision)
            self.assertEqual(response.status_code, 409, response.data)
            self.assertEqual(response.data["code"], "stale_program_launch")
        self.program.refresh_from_db()
        self.assertTrue(self.program.draft)

    def test_retry_after_success_does_not_publish_a_second_form_version(self):
        config = self.configure()
        revision = self.state()["revision"]
        self.assertEqual(self.publish(revision).status_code, 200)
        self.assertEqual(self.publish(revision).status_code, 200)
        config.refresh_from_db()
        self.assertEqual(config.published_version, 1)

    def test_failure_between_registration_and_program_save_rolls_back_both(self):
        config = self.configure()
        revision = self.state()["revision"]
        with patch.object(
            PartnerProgram, "save", side_effect=RuntimeError("simulated failure")
        ):
            with self.assertRaises(RuntimeError):
                publish_program(self.program.pk, self.creator, revision)
        config.refresh_from_db()
        self.program.refresh_from_db()
        self.assertIsNone(config.published)
        self.assertEqual(config.published_version, 0)
        self.assertTrue(self.program.draft)

    def test_noncompetitive_program_requires_no_competition_configuration(self):
        self.program = PartnerProgram.objects.get(
            pk=self.create(format="noncompetitive").data["id"]
        )
        self.url = f"/programs/{self.program.pk}/management/"
        self.configure()
        self.assertEqual(self.publish().status_code, 200)
        self.program.refresh_from_db()
        self.assertFalse(self.program.is_competitive)

    def test_invalid_registration_schema_and_expired_registration_block_launch(self):
        config = self.configure()
        config.draft = {"mode": "other", "fields": []}
        config.save()
        self.program.datetime_registration_ends = timezone.now() - timezone.timedelta(
            days=1
        )
        self.program.save()
        self.assertEqual(
            {r["code"] for r in self.state()["blockers"]}, {"dates", "registration"}
        )
        self.assertEqual(self.publish().status_code, 400)

    def test_program_end_must_follow_start_but_registration_can_continue_after_start(
        self,
    ):
        self.configure()
        self.program.datetime_registration_ends = (
            self.program.datetime_started + timezone.timedelta(days=1)
        )
        self.program.save()
        self.assertTrue(self.state()["can_publish"])
        self.program.datetime_finished = self.program.datetime_started
        self.program.save()
        self.assertEqual([r["code"] for r in self.state()["blockers"]], ["dates"])
        self.assertEqual(self.publish().status_code, 400)

    def test_published_program_keeps_existing_nonnullable_dates_contract(self):
        self.configure()
        self.publish()
        self.program.refresh_from_db()
        response = self.client.patch(
            self.url + "settings/dates/",
            {
                "expected_updated_at": self.program.datetime_updated.isoformat(),
                "datetime_started": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_later_solution_configuration_needs_no_technical_rollout(self):
        self.configure()
        self.publish()
        participant = create_user(is_active=True)
        PartnerProgramUserProfile.objects.create(
            partner_program=self.program, user=participant, partner_program_data={}
        )
        self.client.force_authenticate(participant)
        url = f"/programs/{self.program.pk}/solution-context/"
        self.assertEqual(
            self.client.get(url).data["blocked_reason"], "form_not_configured"
        )
        detail_url = f"/programs/{self.program.pk}/"
        detail = self.client.get(detail_url).data
        self.assertFalse(detail["solution_action_available"])
        self.assertEqual(detail["solution_action_blocked_reason"], "form_not_configured")
        self.program.fields.create(
            name="case",
            label="Кейс",
            field_type="select",
            purpose="case",
            is_required=True,
            show_filter=True,
            options="Кейс 1",
            solution_options=["Кейс 1"],
        )
        self.assertTrue(self.client.get(url).data["can_create"])
        self.assertTrue(self.client.get(detail_url).data["solution_action_available"])
        self.program.solution_creation_enabled = False
        self.program.save(update_fields=["solution_creation_enabled"])
        self.assertEqual(
            self.client.get(url).data["blocked_reason"], "solution_creation_disabled"
        )


@skipUnlessDBFeature("has_select_for_update")
class ProgramLaunchConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.creator = create_user(is_active=True)
        self.creator.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="partner_programs", codename="add_partnerprogram"
            )
        )

    def parallel_posts(self, url, data):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import connections

        barrier = Barrier(2)

        def post(_):
            try:
                client = APIClient()
                client.force_authenticate(
                    type(self.creator).objects.get(pk=self.creator.pk)
                )
                barrier.wait(timeout=10)
                response = client.post(url, data, format="json")
                return response.status_code, response.data
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(post, range(2)))

    def test_concurrent_create_has_one_program_and_manager_assignment(self):
        results = self.parallel_posts(
            "/programs/drafts/",
            dict(name="Concurrent", format="hackathon", idempotency_key=str(uuid4())),
        )
        self.assertEqual(sorted(code for code, _ in results), [200, 201], results)
        self.assertEqual(len({data["id"] for _, data in results}), 1)
        self.assertEqual(PartnerProgram.objects.count(), 1)
        self.assertEqual(PartnerProgram.objects.get().managers.count(), 1)

    def test_concurrent_publication_publishes_registration_once(self):
        from partner_programs.services.program_launch import create_program, readiness

        program, _ = create_program(
            self.creator,
            dict(name="Concurrent", format="hackathon", idempotency_key=uuid4()),
        )
        now = timezone.now()
        program.description = "Description"
        program.datetime_started = now + timezone.timedelta(days=10)
        program.datetime_finished = now + timezone.timedelta(days=30)
        program.datetime_registration_ends = now + timezone.timedelta(days=5)
        program.save()
        config = ProgramRegistration.objects.create(
            program=program, draft={"mode": "native", "fields": []}
        )
        revision = readiness(program.pk, self.creator)["revision"]
        results = self.parallel_posts(
            f"/programs/{program.pk}/management/publish/", {"revision": revision}
        )
        self.assertEqual([code for code, _ in results], [200, 200], results)
        config.refresh_from_db()
        program.refresh_from_db()
        self.assertFalse(program.draft)
        self.assertEqual(config.published_version, 1)

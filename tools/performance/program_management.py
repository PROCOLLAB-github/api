"""Opt-in HTTP benchmark: python manage.py test tools.performance.program_management."""

import http.client
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from math import ceil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework_simplejwt.tokens import AccessToken

from partner_programs.models import PartnerProgramUserProfile
from project_rates.models import ProjectExpertAssignment

from .fixtures import (
    ANSWERS,
    CASE_NAMES,
    ENROLLMENT_SAMPLES,
    FIELD_ID,
    SCALES,
    XLSX_CONTENT_TYPE,
    ProgramFixture,
)

LOOPBACK = "127.0.0.1"
PAGE_SIZE = 25
HTTP_TIMEOUT_SECONDS = 25
READ_LEVELS = ((1, 24), (8, 24))


def require_isolated_settings():
    if (
        settings.SETTINGS_MODULE != "procollab.settings_ci"
        or connection.vendor != "postgresql"
        or connection.settings_dict["HOST"] != LOOPBACK
        or connection.settings_dict["TEST"]["NAME"] != "test_procollab_ci"
        or settings.EMAIL_BACKEND != "django.core.mail.backends.locmem.EmailBackend"
        or settings.CELERY_BROKER_URL != "memory://"
        or settings.AUTOPOSTING_ON
    ):
        raise RuntimeError("Benchmark requires isolated PostgreSQL CI settings")


def load_tests(loader, tests, pattern):
    # Refuse other settings before the test runner sets up a database.
    require_isolated_settings()
    return tests


def require(condition, description):
    if not condition:
        raise AssertionError(description)


@dataclass(frozen=True)
class Request:
    path: str
    token: str | None
    body: bytes | None = None


@dataclass(frozen=True)
class Response:
    elapsed_ms: float
    status: int | None = None
    content_type: str = ""
    body: bytes = b""
    transport_error: str = ""


def nearest_rank(values, fraction):
    return values[ceil(len(values) * fraction) - 1] if values else None


def error_name(error):
    # Keep tokens, response bodies and exception paths out of the artifact.
    if isinstance(error, AssertionError) and error.args:
        return str(error.args[0])
    return type(error).__name__


def fetch(request, port):
    headers = {"Accept": "*/*"}
    if request.token:
        headers["Authorization"] = f"Bearer {request.token}"
    if request.body is not None:
        headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(LOOPBACK, port, timeout=HTTP_TIMEOUT_SECONDS)
    started = perf_counter()
    try:
        conn.request(
            "GET" if request.body is None else "POST",
            request.path,
            request.body,
            headers,
        )
        with conn.getresponse() as result:
            body = result.read()
            return Response(
                (perf_counter() - started) * 1000,
                result.status,
                result.headers.get_content_type(),
                body,
            )
    except (OSError, http.client.HTTPException) as error:
        return Response(
            (perf_counter() - started) * 1000, transport_error=type(error).__name__
        )
    finally:
        conn.close()


def validated(response, validate):
    if response.transport_error:
        return response.transport_error
    if response.status is None or not 200 <= response.status < 300:
        return f"HTTP {response.status}"
    try:
        validate(response)
    except Exception as error:
        return error_name(error)
    return None


def json_response(check):
    def validate(response):
        require(response.content_type == "application/json", "Unexpected JSON media type")
        check(json.loads(response.body))

    return validate


def check_xlsx_headers(response):
    require(response.content_type == XLSX_CONTENT_TYPE, "Unexpected XLSX media type")
    require(response.body.startswith(b"PK\x03\x04"), "Response is not a ZIP workbook")


class ProgramManagementPerformance(LiveServerTestCase):
    host = LOOPBACK

    @classmethod
    def setUpClass(cls):
        require_isolated_settings()
        if connection.settings_dict["NAME"] != "test_procollab_ci":
            raise RuntimeError("Benchmark requires Django's test database")
        media_root = cls.enterClassContext(TemporaryDirectory(prefix="procollab-perf-"))
        cls.enterClassContext(
            override_settings(
                ALLOWED_HOSTS=[LOOPBACK],
                MEDIA_ROOT=media_root,
                STORAGES={
                    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
                    "staticfiles": settings.STORAGES["staticfiles"],
                },
            )
        )
        super().setUpClass()

    def test_program_management(self):
        profile = os.environ.get("PROCOLLAB_PERF_PROFILE", "small")
        require(profile in SCALES, "Unknown PROCOLLAB_PERF_PROFILE")
        output = os.environ.get("PROCOLLAB_PERF_OUTPUT")
        require(bool(output), "Set PROCOLLAB_PERF_OUTPUT to a JSON report path")
        report = {
            "schema_version": 1,
            "implementation": os.environ.get(
                "PROCOLLAB_PERF_IMPLEMENTATION", "unspecified"
            ),
            "profile": profile,
            "fixture": {},
            "scenarios": [],
            "errors": [],
        }
        self.report = report
        self.read_concurrency = (
            (*READ_LEVELS, (24, 72)) if profile == "pressure" else READ_LEVELS
        )
        mail.get_connection()
        cache.clear()
        try:
            self.fixture = ProgramFixture(SCALES[profile])
            self.manager_token = str(AccessToken.for_user(self.fixture.manager))
            self.report["fixture"] = self.fixture.summary()
            self.run_read_scenarios()
            self.run_allocation_preview()
            self.run_enrollment()
            require(not mail.outbox, "Benchmark caused an unexpected email")
            self.run_signup_and_confirmation()
        except Exception as error:
            report["errors"].append(error_name(error))
            raise
        finally:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        failures = [
            scenario["name"]
            for scenario in report["scenarios"]
            if scenario["errors"] or scenario["warmup_errors"]
        ]
        self.assertFalse(failures, f"Failed HTTP scenarios: {', '.join(failures)}")

    def endpoint(self, name):
        return reverse(f"partner_programs:{name}", args=(self.fixture.program.pk,))

    def request(self, path, *, query=None, token=None, payload=None):
        if query:
            path += "?" + urlencode(query)
        return Request(
            path,
            self.manager_token if token is None else token,
            None if payload is None else json.dumps(payload).encode(),
        )

    def run_scenario(
        self,
        name,
        requests,
        concurrency,
        validate,
        expected,
        *,
        warmup,
        warmup_check=None,
    ):
        def run_request(request):
            return fetch(request, self.server_thread.port)

        warmup_error = validated(run_request(warmup), warmup_check or validate)
        with ThreadPoolExecutor(max_workers=concurrency) as workers:
            started = perf_counter()
            responses = list(workers.map(run_request, requests))
            wall_seconds = perf_counter() - started
        errors = Counter(
            error
            for response in responses
            if (error := validated(response, validate)) is not None
        )
        latency = sorted(
            response.elapsed_ms for response in responses if response.status is not None
        )
        sizes = [
            len(response.body) for response in responses if response.status is not None
        ]
        self.report["scenarios"].append(
            {
                "name": name,
                "samples": len(responses),
                "concurrency": concurrency,
                "wall_seconds": wall_seconds,
                "requests_per_second": len(responses) / wall_seconds,
                "latency_ms": {
                    f"p{percentile}": nearest_rank(latency, percentile / 100)
                    for percentile in (50, 95, 99)
                },
                "response_bytes": (
                    {"min": min(sizes), "median": median(sizes), "max": max(sizes)}
                    if sizes
                    else None
                ),
                "status_counts": dict(
                    Counter(
                        str(response.status)
                        for response in responses
                        if response.status is not None
                    )
                ),
                "errors": dict(errors),
                "expected": expected,
                "warmup_errors": [warmup_error] if warmup_error else [],
            }
        )

    def read_levels(self, name, request, check, expected):
        for concurrency, samples in self.read_concurrency:
            self.run_scenario(
                name,
                [request] * samples,
                concurrency,
                json_response(check),
                expected,
                warmup=request,
            )

    def page_check(self, data, count, total, page_size):
        require(data["count"] == count, "Unexpected filtered row count")
        require(data["total_count"] == total, "Unexpected total row count")
        require(len(data["results"]) == page_size, "Unexpected page length")
        require(
            len({row["id"] for row in data["results"]}) == page_size, "Duplicate rows"
        )

    def run_read_scenarios(self):
        fixture = self.fixture
        participants = fixture.scale.participants
        projects = fixture.scale.projects
        participants_path = self.endpoint("management-participants")
        query = {"limit": PAGE_SIZE}

        self.read_levels(
            "participants_list",
            self.request(participants_path, query=query),
            lambda data: self.page_check(data, participants, participants, PAGE_SIZE),
            {"total": participants, "page_size": PAGE_SIZE},
        )

        detail_registration = fixture.registrations[0]
        detail_email = detail_registration.user.email
        detail_label, detail_answer = fixture.answers_by_email[detail_email]

        def check_participant(data):
            self.page_check(data, 1, participants, 1)
            detail = data["results"][0]
            require(detail["id"] == detail_registration.pk, "Unexpected participant")
            require(detail["email"] == detail_email, "Unexpected participant email")
            require(
                detail["registration_answers"]
                == [{"label": detail_label, "value": detail_answer}],
                "Participant answer was not preserved",
            )

        self.read_levels(
            "participant_lookup",
            self.request(participants_path, query={"search": detail_email}),
            check_participant,
            {"total": participants, "matches": 1, "answers": 1},
        )

        def check_search(data):
            self.page_check(data, participants // 2, participants, PAGE_SIZE)
            require(
                all(row["region"] == "Москва" for row in data["results"]),
                "Unexpected participant region after filtering",
            )

        self.read_levels(
            "participant_search_filter",
            self.request(
                participants_path,
                query={
                    **query,
                    "search": "perf-participant",
                    "region_scope": "selected",
                    "region": "Москва",
                    "activity": "active",
                },
            ),
            check_search,
            {"total": participants, "matches": participants // 2, "page_size": PAGE_SIZE},
        )

        def check_projects(data):
            self.page_check(data, projects, projects, PAGE_SIZE)
            require(
                {row["project_id"] for row in data["results"]}
                == {project.pk for project in fixture.projects[:PAGE_SIZE]},
                "Unexpected projects on the first page",
            )

        self.read_levels(
            "projects_list",
            self.request(self.endpoint("management-projects"), query=query),
            check_projects,
            {"total": projects, "page_size": PAGE_SIZE},
        )

        def check_analytics(data):
            summary = data["summary"]
            funnel = data["participant_funnel"]
            require(
                summary["participants"]["total"] == participants,
                "Unexpected analytics participants",
            )
            require(
                summary["projects"]["total"] == projects, "Unexpected analytics projects"
            )
            require(
                summary["experts"]["total"] == fixture.scale.experts,
                "Unexpected analytics experts",
            )
            require(
                funnel["with_team"] == projects * 3, "Unexpected analytics team members"
            )
            require(
                funnel["submitted_project_creators"] == fixture.submitted_count,
                "Unexpected submitted project creators",
            )

        self.read_levels(
            "management_analytics_overview",
            self.request(self.endpoint("manager-overview")),
            check_analytics,
            {
                "participants": participants,
                "projects": projects,
                "experts": fixture.scale.experts,
                "with_team": projects * 3,
                "submitted_project_creators": fixture.submitted_count,
            },
        )

        request = self.request(self.endpoint("management-participants-export"))
        self.run_scenario(
            "participants_excel",
            [request] * 5,
            1,
            check_xlsx_headers,
            {"participants": participants, "answers": participants},
            warmup=request,
            warmup_check=self.check_workbook,
        )

    def check_workbook(self, response):
        check_xlsx_headers(response)
        workbook = load_workbook(BytesIO(response.body), read_only=True)
        try:
            require(
                workbook.sheetnames == ["Участники", "Анкеты"], "Unexpected XLSX sheets"
            )
            participants = workbook["Участники"].values
            answers = workbook["Анкеты"].values
            require(
                next(participants)[2] == "Почта", "Unexpected XLSX participants header"
            )
            require(
                next(answers)[1:] == ("Почта", "Поле анкеты", "Ответ"),
                "Unexpected XLSX answers header",
            )
            require(
                Counter(row[2] for row in participants)
                == Counter(self.fixture.answers_by_email.keys()),
                "XLSX participant rows were not preserved",
            )
            require(
                Counter((row[1], row[2], row[3]) for row in answers)
                == Counter(
                    (email, *answer)
                    for email, answer in self.fixture.answers_by_email.items()
                ),
                "XLSX answer rows were not preserved",
            )
        finally:
            workbook.close()

    def run_allocation_preview(self):
        fixture = self.fixture
        project_cases = {
            project.pk: CASE_NAMES[i % 2]
            for i, project in enumerate(fixture.projects[: fixture.submitted_count])
        }
        allowed = {
            pool["case_name"]: set(pool["expert_ids"]) for pool in fixture.case_pools
        }
        expert_ids = sorted(set().union(*allowed.values()))
        expected_additions = 2 * fixture.submitted_count - len(
            fixture.existing_assignments
        )
        request = self.request(
            f"/programs/{fixture.program.pk}/management/expert-allocation/",
            payload={
                "expert_ids": expert_ids,
                "case_pools": fixture.case_pools,
                "seed": 17,
            },
        )

        def check_preview(data):
            require(not data["shortages"], "Allocation preview has shortages")
            require(bool(data["plan_token"]), "Allocation preview has no plan")
            rows = data["assignments"]
            proposed = {(row["project_id"], row["expert_id"]) for row in rows}
            require(
                len(rows) == len(proposed) == expected_additions,
                "Unexpected allocation size",
            )
            require(
                not proposed.intersection(fixture.existing_assignments),
                "Allocation repeats existing assignments",
            )
            require(
                all(
                    expert in allowed[project_cases[project]]
                    for project, expert in proposed
                ),
                "Allocation assigned an expert outside the case pool",
            )
            require(
                Counter(project for project, _ in proposed | fixture.existing_assignments)
                == Counter({project: 2 for project in project_cases}),
                "Preview did not fill every submitted project",
            )

        for concurrency, samples in ((1, 6), (2, 6)):
            self.run_scenario(
                "distribution_preview",
                [request] * samples,
                concurrency,
                json_response(check_preview),
                {
                    "new_assignments": expected_additions,
                    "shortages": 0,
                    "projects": fixture.submitted_count,
                },
                warmup=request,
            )
        actual = ProjectExpertAssignment.objects.filter(
            partner_program=fixture.program
        ).values_list("project_id", "expert_id")
        require(
            set(actual) == fixture.existing_assignments,
            "Preview changed existing assignments",
        )

    def run_enrollment(self):
        fixture = self.fixture
        payload = {"version": 1, "answers": {FIELD_ID: ANSWERS[0]}}
        requests = [
            self.request(
                f"/programs/{fixture.program.pk}/registration/",
                token=str(AccessToken.for_user(user)),
                payload=payload,
            )
            for user in fixture.enrollees
        ]
        ids = [user.pk for user in fixture.enrollees]
        rows = PartnerProgramUserProfile.objects.filter(partner_program=fixture.program)
        enrollments = rows.filter(user_id__in=ids)
        require(not enrollments.exists(), "Enrollment fixture already has registrations")

        def check_enrollment(data):
            require(data["enrolled"] is True, "Participant was not enrolled")
            require(
                data["program_id"] == fixture.program.pk, "Enrolled in unexpected program"
            )

        self.run_scenario(
            "authenticated_enrollment",
            requests[1:],
            4,
            json_response(check_enrollment),
            {
                "new_registrations": ENROLLMENT_SAMPLES,
                "answers_per_registration": 1,
            },
            warmup=requests[0],
        )
        require(
            {row.user_id for row in enrollments} == set(ids),
            "Enrollment did not persist one registration per account",
        )
        require(
            all(
                row.partner_program_data == payload["answers"]
                and row.registration_schema == fixture.registration_schema
                for row in enrollments
            ),
            "Enrollment did not preserve answers and published schema",
        )
        require(
            rows.count() == fixture.scale.participants + ENROLLMENT_SAMPLES + 1,
            "Unexpected number of registrations after enrollment",
        )

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.BCryptSHA256PasswordHasher"]
    )
    def run_signup_and_confirmation(self):
        fixture = self.fixture
        # Five measurements and one warm-up per endpoint fit the live IP limit of 12.
        emails = [f"perf-signup-{index}@example.test" for index in range(6)]
        root = f"/programs/{fixture.program.pk}/registration/"
        answers = {FIELD_ID: ANSWERS[1]}
        password = "benchmark-river-park-837"
        signups = [
            self.request(
                root + "signup/",
                token="",
                payload={
                    "version": 1,
                    "answers": answers,
                    "first_name": "Мария",
                    "last_name": "Иванова",
                    "email": email,
                    "birthday": "2000-01-01",
                    "password": password,
                    "repeat_password": password,
                    "accept_policy": True,
                    "accept_age": True,
                },
            )
            for email in emails
        ]

        def check_signup(data):
            require(data.get("email_pending") is True, "Signup did not wait for email")
            require("access" not in data, "Unconfirmed signup returned an access token")

        self.run_scenario(
            "new_account_signup",
            signups[1:],
            5,
            json_response(check_signup),
            {"emails": 5, "password_hasher": "BCryptSHA256", "delivery": "locmem"},
            warmup=signups[0],
        )
        tokens = {}
        require(len(mail.outbox) == len(emails), "Unexpected number of signup emails")
        for message in mail.outbox:
            links = [
                line.strip()
                for line in message.body.splitlines()
                if "#confirmation=" in line
            ]
            require(len(links) == 1, "Signup email must contain one confirmation link")
            link = urlsplit(links[0])
            require(
                link.path == f"/program-registration/{fixture.program.pk}",
                "Confirmation link belongs to the wrong program",
            )
            tokens[message.to[0]] = parse_qs(link.fragment)["confirmation"][0]
        require(set(tokens) == set(emails), "Emails sent to the wrong recipients")
        confirmations = [
            self.request(root + "confirm/", token="", payload={"token": tokens[email]})
            for email in emails
        ]

        def check_confirmation(data):
            require(data.get("enrolled") is True, "Confirmed account was not enrolled")
            require(data.get("program_id") == fixture.program.pk, "Wrong program")
            require(bool(data.get("access")), "Confirmed account has no access token")

        self.run_scenario(
            "confirm_new_account",
            confirmations[1:],
            5,
            json_response(check_confirmation),
            {"confirmed_registrations": 5},
            warmup=confirmations[0],
        )
        registrations = PartnerProgramUserProfile.objects.filter(
            partner_program=fixture.program, user__email__in=emails
        ).select_related("user")
        require(registrations.count() == len(emails), "Confirmation lost a registration")
        require(
            all(
                row.user.is_active
                and row.partner_program_data == answers
                and row.registration_schema == fixture.registration_schema
                for row in registrations
            ),
            "Confirmation did not preserve answers and activate the account",
        )
        require(
            registrations.first().user.check_password(password),
            "New account cannot authenticate with its original password",
        )

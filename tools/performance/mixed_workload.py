"""Opt-in mixed HTTP workload on the isolated PostgreSQL CI settings."""

import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from itertools import accumulate
from pathlib import Path
from threading import Barrier
from time import perf_counter
from unittest import skipUnless

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from openpyxl import load_workbook
from rest_framework_simplejwt.tokens import AccessToken

from partner_programs.models import PartnerProgramUserProfile, PendingProgramRegistration

from . import program_management as perf
from .fixtures import (
    ANSWERS,
    ENROLLMENT_SAMPLES,
    FIELD_ID,
    FIELD_LABEL,
    SCALES,
    ProgramFixture,
)

OPT_IN = "PROCOLLAB_PERF_MIXED"
OVERVIEW = "management_analytics_overview"
PARTICIPANTS = "participants_list"
EXCEL = "participants_excel"
ENROLLMENT = "authenticated_enrollment"
SIGNUP = "new_account_signup"
EXPECTED_STATUS = {OVERVIEW: 200, PARTICIPANTS: 200, EXCEL: 200, ENROLLMENT: 200, SIGNUP: 201}
BARRIER_TIMEOUT_SECONDS = 15
WRITER_CLIENTS = 6


def load_tests(loader, tests, pattern):
    if os.environ.get(OPT_IN) == "1":
        perf.require_isolated_settings()
    return tests


@dataclass(frozen=True)
class Operation:
    scenario: str
    request: perf.Request
    email: str = ""


@dataclass(frozen=True)
class Observation:
    operation: Operation
    response: perf.Response
    start: float
    end: float


def summarize(observations, errors):
    latency = sorted(observation.response.elapsed_ms for observation in observations)
    statuses = Counter(
        str(observation.response.status)
        for observation in observations
        if observation.response.status is not None
    )
    return {
        "samples": len(observations),
        "latency_ms": {
            f"p{percentile}": perf.nearest_rank(latency, percentile / 100)
            for percentile in (50, 95, 99)
        },
        "status_counts": dict(statuses),
        "errors": dict(errors),
    }


def overlap_seconds(left, right):
    return max(0, min(left.end, right.end) - max(left.start, right.start))


@skipUnless(os.environ.get(OPT_IN) == "1", f"Set {OPT_IN}=1 for the mixed HTTP workload")
@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.BCryptSHA256PasswordHasher"]
)
class MixedProgramWorkloadTests(perf.ProgramManagementPerformance):
    # Reuse the isolated live server without collecting the original benchmark.
    test_program_management = None

    def test_mixed_program_workload(self):
        output = os.environ.get("PROCOLLAB_PERF_OUTPUT")
        perf.require(bool(output), "Set PROCOLLAB_PERF_OUTPUT to a JSON report path")
        self.report = {
            "schema_version": 1,
            "implementation": os.environ.get(
                "PROCOLLAB_PERF_IMPLEMENTATION", "unspecified"
            ),
            "profile": "pressure",
            "http_socket_timeout_seconds": perf.HTTP_TIMEOUT_SECONDS,
            "start_barrier_timeout_seconds": BARRIER_TIMEOUT_SECONDS,
            "fixture": {},
            "phases": [],
            "verification": {},
            "errors": [],
        }
        try:
            mail.get_connection()
            cache.clear()
            self.fixture = ProgramFixture(SCALES["pressure"])
            self.report["fixture"] = self.fixture.summary()
            self.manager_token = str(AccessToken.for_user(self.fixture.manager))
            self.run_workload()
            failed = [phase["name"] for phase in self.report["phases"] if phase["errors"]]
            perf.require(not failed, f"Failed HTTP phases: {', '.join(failed)}")
        except Exception as error:
            self.report["errors"].append(perf.error_name(error))
            raise
        finally:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    def run_workload(self):
        overview = Operation(OVERVIEW, self.request(self.endpoint("manager-overview")))
        participants = Operation(
            PARTICIPANTS,
            self.request(
                self.endpoint("management-participants"),
                query={"limit": perf.PAGE_SIZE, "order": "registration"},
            ),
        )
        excel = Operation(
            EXCEL, self.request(self.endpoint("management-participants-export"))
        )
        overview_clients = [(overview,) * 2] * 8
        participants_clients = [(participants,) * 2] * 8
        excel_clients = [(excel,)] * 2
        writers = self.writer_clients()
        self.run_phase("control_overview", overview_clients)
        self.run_phase("control_participants", participants_clients)
        self.run_phase("control_excel", excel_clients)
        self.run_phase(
            "mixed", overview_clients + participants_clients + writers + excel_clients
        )
        # This full export must contain every committed enrollment after the mixed phase.
        self.run_phase("post_write", [(excel,)], enrolled=set(self.enrollment_answers))
        self.check_persistence()

    def writer_clients(self):
        root = f"/programs/{self.fixture.program.pk}/registration/"
        self.enrollment_answers = {}
        clients = [[] for _ in range(WRITER_CLIENTS)]
        for index, user in enumerate(self.fixture.enrollees[:ENROLLMENT_SAMPLES]):
            answer = ANSWERS[index % len(ANSWERS)]
            self.enrollment_answers[user.email] = (FIELD_LABEL, answer)
            request = self.request(
                root,
                token=str(AccessToken.for_user(user)),
                payload={"version": 1, "answers": {FIELD_ID: answer}},
            )
            clients[index % len(clients)].append(Operation(ENROLLMENT, request, user.email))

        self.signup_answers = {}
        # Two public requests from the live server's loopback IP under the 12/min throttle.
        for index, client in enumerate(clients[:2]):
            email = f"perf-mixed-signup-{index}@example.test"
            answers = {FIELD_ID: ANSWERS[index]}
            self.signup_answers[email] = answers
            password = "benchmark-river-park-837"
            request = self.request(
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
            client.append(Operation(SIGNUP, request, email))
        return clients

    def run_phase(self, name, clients, *, enrolled=frozenset()):
        barrier = Barrier(len(clients), timeout=BARRIER_TIMEOUT_SECONDS)

        def run_client(operations):
            barrier.wait()
            observations = []
            for operation in operations:
                start = perf_counter()
                response = perf.fetch(operation.request, self.server_thread.port)
                observations.append(Observation(operation, response, start, perf_counter()))
            return observations

        with ThreadPoolExecutor(max_workers=len(clients)) as executor:
            results_by_client = list(executor.map(run_client, clients))

        observations = [row for client in results_by_client for row in client]
        first_requests = [client[0] for client in results_by_client]
        start = min(row.start for row in observations)
        elapsed = max(row.end for row in observations) - start
        events = sorted(
            event
            for row in observations
            for event in ((row.start, 1), (row.end, -1))
        )
        groups = {
            scenario: [row for row in observations if row.operation.scenario == scenario]
            for scenario in EXPECTED_STATUS
        }
        started_clients = Counter(client[0].scenario for client in clients)
        planned_samples = Counter(operation.scenario for client in clients for operation in client)
        write_rows = groups[ENROLLMENT]
        phase_errors = Counter()
        scenarios = []
        for scenario, rows in groups.items():
            if not rows:
                continue
            errors = Counter(
                error
                for row in rows
                if (error := self.validate_observation(row, write_rows, enrolled)) is not None
            )
            phase_errors.update(errors)
            scenarios.append(
                {
                    "name": scenario,
                    "starting_clients": started_clients[scenario],
                    "planned_samples": planned_samples[scenario],
                    "expected_status": EXPECTED_STATUS[scenario],
                    "request_window_seconds": {
                        "first_start": min(row.start for row in rows) - start,
                        "last_end": max(row.end for row in rows) - start,
                    },
                    **summarize(rows, errors),
                }
            )
        phase = {
            "name": name,
            "starting_clients": len(clients),
            "peak_in_flight_requests": max(accumulate(change for _, change in events)),
            "initial_start_spread_ms": (max(row.start for row in first_requests) - start)
            * 1000,
            "wall_seconds": elapsed,
            "requests_per_second": len(observations) / elapsed,
            "scenarios": scenarios,
        }
        if write_rows:
            phase["native_enrollment_overlap"] = {}
            for scenario in (OVERVIEW, PARTICIPANTS, EXCEL, SIGNUP):
                overlaps = [
                    overlap_seconds(row, write)
                    for row in groups[scenario]
                    for write in write_rows
                ]
                phase["native_enrollment_overlap"][scenario] = {
                    "overlapping_pairs": sum(value > 0 for value in overlaps),
                    "longest_overlap_seconds": max(overlaps, default=0),
                }
                if scenario != SIGNUP and not any(overlaps):
                    phase_errors[f"No HTTP overlap between {scenario} and enrollment"] += 1
        phase.update(summarize(observations, phase_errors))
        self.report["phases"].append(phase)

    def validate_observation(self, row, write_rows, enrolled):
        scenario = row.operation.scenario
        response = row.response
        if response.transport_error:
            return response.transport_error
        if response.status != EXPECTED_STATUS[scenario]:
            return f"HTTP {response.status}"

        def validate(result):
            # A commit may precede its HTTP response. A read can see any subset of
            # enrollments whose requests overlap it, plus all commits already acknowledged.
            required = enrolled | {
                write.operation.email
                for write in write_rows
                if write.response.status == EXPECTED_STATUS[ENROLLMENT] and write.end <= row.start
            }
            allowed = enrolled | {
                write.operation.email for write in write_rows if write.start < row.end
            }
            if scenario == EXCEL:
                self.check_snapshot_workbook(result, required, allowed)
            else:
                perf.json_response(
                    lambda data: self.check_json(row.operation, data, required, allowed)
                )(result)

        return perf.validated(response, validate)

    def check_json(self, operation, data, required, allowed):
        fixture = self.fixture
        scenario = operation.scenario
        minimum = fixture.scale.participants + len(required)
        maximum = fixture.scale.participants + len(allowed)
        if scenario == ENROLLMENT:
            perf.require(data["enrolled"] is True, "Participant was not enrolled")
            perf.require(data["program_id"] == fixture.program.pk, "Wrong enrollment program")
        elif scenario == SIGNUP:
            perf.require(data.get("email_pending") is True, "Signup did not wait for email")
            perf.require("access" not in data, "Unconfirmed signup returned an access token")
            perf.require(data.get("email") == operation.email, "Wrong signup recipient")
        elif scenario == OVERVIEW:
            summary = data["summary"]
            funnel = data["participant_funnel"]
            perf.require(
                minimum <= summary["participants"]["total"] <= maximum,
                "Overview participant count outside snapshot bounds",
            )
            perf.require(summary["projects"]["total"] == fixture.scale.projects, "Wrong project total")
            perf.require(summary["experts"]["total"] == fixture.scale.experts, "Wrong expert total")
            perf.require(funnel["with_team"] == fixture.scale.projects * 3, "Wrong team member count")
            perf.require(
                funnel["submitted_project_creators"] == fixture.submitted_count,
                "Wrong submitted project creator count",
            )
        else:
            # These are separate SQL queries and may observe different committed counts.
            for key in ("count", "total_count"):
                perf.require(minimum <= data[key] <= maximum, "List count outside snapshot bounds")
            rows = data["results"]
            seeded_emails = list(fixture.answers_by_email)[: perf.PAGE_SIZE]
            perf.require([row["email"] for row in rows] == seeded_emails, "Wrong participant page")
            for row in rows:
                label, answer = fixture.answers_by_email[row["email"]]
                perf.require(
                    row["registration_answers"] == [{"label": label, "value": answer}],
                    "Participant list lost a saved answer",
                )

    def check_snapshot_workbook(self, response, required, allowed):
        perf.check_xlsx_headers(response)
        workbook = load_workbook(BytesIO(response.body), read_only=True)
        try:
            perf.require(workbook.sheetnames == ["Участники", "Анкеты"], "Unexpected XLSX sheets")
            participants = workbook["Участники"].values
            answers = workbook["Анкеты"].values
            perf.require(next(participants)[2] == "Почта", "Unexpected XLSX participant header")
            perf.require(
                next(answers)[1:] == ("Почта", "Поле анкеты", "Ответ"), "Unexpected XLSX answer header"
            )
            emails = Counter(row[2] for row in participants)
            seeded_answers = self.fixture.answers_by_email
            new_emails = emails.keys() - seeded_answers.keys()
            perf.require(required <= new_emails <= allowed, "XLSX snapshot outside enrollment bounds")
            expected = {**seeded_answers, **{email: self.enrollment_answers[email] for email in new_emails}}
            perf.require(emails == Counter(expected.keys()), "XLSX lost or duplicated a participant")
            perf.require(
                Counter((row[1], row[2], row[3]) for row in answers)
                == Counter((email, *answer) for email, answer in expected.items()),
                "XLSX answer sheet does not match its participants",
            )
        finally:
            workbook.close()

    def check_persistence(self):
        fixture = self.fixture
        profiles = PartnerProgramUserProfile.objects.filter(partner_program=fixture.program)
        final_count = profiles.count()
        self.report["verification"]["registrations"] = {
            "before": fixture.scale.participants,
            "after": final_count,
            "growth": final_count - fixture.scale.participants,
        }
        perf.require(
            final_count == fixture.scale.participants + len(self.enrollment_answers),
            "Unexpected registration growth",
        )
        enrolled = profiles.filter(user__email__in=self.enrollment_answers).select_related("user")
        perf.require(
            Counter(row.user.email for row in enrolled) == Counter(self.enrollment_answers.keys()),
            "Expected one registration per enrolled account",
        )
        perf.require(
            all(
                row.partner_program_data == {FIELD_ID: self.enrollment_answers[row.user.email][1]}
                and row.registration_schema == fixture.registration_schema
                for row in enrolled
            ),
            "Enrollment lost its saved answer or published form",
        )
        pending = list(
            PendingProgramRegistration.objects.filter(program=fixture.program).select_related("user")
        )
        perf.require(
            Counter(row.user.email for row in pending) == Counter(self.signup_answers.keys()),
            "Unexpected pending signup accounts",
        )
        perf.require(
            all(
                not row.user.is_active
                and row.confirmed_at is None
                and row.delivery_status == "sent"
                and row.answers == self.signup_answers[row.user.email]
                and row.schema == fixture.registration_schema
                for row in pending
            ),
            "Pending signup lost its answers or confirmation state",
        )
        perf.require(
            Counter(tuple(message.to) for message in mail.outbox)
            == Counter((email,) for email in self.signup_answers),
            "Unexpected local confirmation email recipients",
        )
        self.report["verification"].update(
            enrollment_answers=len(enrolled),
            pending_signups=len(pending),
            signup_password_hasher="BCryptSHA256",
            local_confirmation_emails=len(mail.outbox),
        )

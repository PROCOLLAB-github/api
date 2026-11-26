"""Opt-in mixed HTTP workload on the isolated PostgreSQL CI settings."""

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from itertools import accumulate
from pathlib import Path
from statistics import median
from threading import Barrier
from time import perf_counter, sleep, time
from unittest import skipUnless
from unittest.mock import patch
from uuid import UUID
from zoneinfo import ZoneInfo

from celery import Celery
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from openpyxl import load_workbook
from rest_framework_simplejwt.tokens import AccessToken

from partner_programs.models import (
    ParticipantExportJob,
    PartnerProgramUserProfile,
    PendingProgramRegistration,
)

from . import export_queue_worker as worker
from . import program_management as perf
from .fixtures import (
    ANSWERS,
    ENROLLMENT_SAMPLES,
    FIELD_ID,
    FIELD_LABEL,
    SCALES,
    ProgramFixture,
    build_users,
    synthetic_user,
)

OPT_IN = worker.ENABLED
OVERVIEW = "management_analytics_overview"
PARTICIPANTS = "participants_list"
EXCEL = "participants_excel"
ACCEPT = "participant_export_acceptance"
POLL = "participant_export_poll"
DOWNLOAD = "participant_export_download"
EXPORT_STATUSES = {"queued", "ready", "failed", "expired"}
ENROLLMENT = "authenticated_enrollment"
SIGNUP = "new_account_signup"
EXPECTED_STATUS = {
    OVERVIEW: 200,
    PARTICIPANTS: 200,
    EXCEL: 200,
    ENROLLMENT: 200,
    SIGNUP: 201,
    ACCEPT: 202,
    POLL: 200,
    DOWNLOAD: 200,
}
BARRIER_TIMEOUT_SECONDS = 15
WRITER_CLIENTS = 6
POLL_INTERVAL_SECONDS = 3
EXPORT_TIMEOUT_SECONDS = 120
WORKER_READY_TIMEOUT_SECONDS = 45
MOSCOW = ZoneInfo("Europe/Moscow")


def load_tests(loader, tests, pattern):
    if os.environ.get(OPT_IN) == "1":
        perf.require_isolated_settings()
        perf.require(os.environ.get("GITHUB_ACTIONS") == "true", "Run this benchmark on GitHub Actions")
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


@dataclass(frozen=True)
class ExportWindow:
    start: float
    end: float


@dataclass
class ExportAttempt:
    start: float
    observations: list[Observation] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    job_id: UUID | None = None
    workbook: Observation | None = None
    error: str | None = None


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
        "median_ms": median(latency) if latency else None,
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

    def test_participant_export_queue(self):
        output = os.environ.get("PROCOLLAB_PERF_OUTPUT")
        perf.require(bool(output), "Set PROCOLLAB_PERF_OUTPUT to a JSON report path")
        mode = os.environ.get("PROCOLLAB_PERF_EXPORT_MODE")
        perf.require(mode in {"sync", "queued"}, "Expected sync or queued export mode")
        self.queued = mode == "queued"
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock_offset = time() - perf_counter()
        self.report = {
            "schema_version": 2,
            "mode": mode,
            "order": os.environ.get("PROCOLLAB_PERF_ORDER"),
            "implementation": os.environ.get(
                "PROCOLLAB_PERF_IMPLEMENTATION", "unspecified"
            ),
            "profile": "pressure",
            "mixed_export_clients": 2,
            "writer_clients": WRITER_CLIENTS,
            "distinct_export_organizers": 2,
            "heavy_export_writer_limit": 1 if self.queued else None,
            "queued_poll_interval_seconds": POLL_INTERVAL_SECONDS if self.queued else None,
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
            self.expected_participants = self.participant_values(self.fixture.registrations)
            if self.queued:
                self.start_export_worker(output_path.parent)
            self.run_workload()
            failed = [phase["name"] for phase in self.report["phases"] if phase["errors"]]
            perf.require(not failed, f"Failed HTTP phases: {', '.join(failed)}")
        except Exception as error:
            self.report["errors"].append(perf.error_name(error))
            raise
        finally:
            output_path.write_text(
                json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    def start_export_worker(self, results):
        from partner_programs.tasks import generate_participant_export

        media_root = Path(settings.MEDIA_ROOT)
        ready_path = media_root / "worker-ready"
        log = self.enterContext((results / "celery-queued.log").open("w", encoding="utf-8"))
        process = subprocess.Popen(
            [sys.executable, "-m", "tools.performance.export_queue_worker", str(media_root), str(ready_path)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        self.addCleanup(self.stop_worker, process)
        deadline = perf_counter() + WORKER_READY_TIMEOUT_SECONDS
        while not ready_path.exists():
            perf.require(process.poll() is None, "Export Celery worker exited before readiness")
            perf.require(perf_counter() < deadline, "Export Celery worker readiness timed out")
            sleep(0.1)

        publisher = Celery("participant-export-perf", broker=worker.BROKER, set_as_current=False)
        publisher.conf.task_default_queue = worker.QUEUE
        self.addCleanup(publisher.close)

        def send_export(args=None, kwargs=None, **options):
            return publisher.send_task(generate_participant_export.name, args, kwargs, **options)

        # The application keeps its isolated eager Celery settings for confirmation emails.
        # Only the export task's first publish goes through the dedicated Redis transport.
        self.enterContext(patch.object(generate_participant_export, "apply_async", side_effect=send_export))
        self.report["queue_worker"] = {
            "pool": "prefork",
            "concurrency": 2,
            "broker": "Redis loopback",
            "storage": "test PostgreSQL",
        }

    @staticmethod
    def stop_worker(process):
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def run_workload(self):
        overview = Operation(OVERVIEW, self.request(self.endpoint("manager-overview")))
        participants = Operation(
            PARTICIPANTS,
            self.request(
                self.endpoint("management-participants"),
                query={"limit": perf.PAGE_SIZE, "order": "registration"},
            ),
        )
        # Concurrent identical requests from one organizer intentionally reuse a job.
        # Use the same two identities in both modes to produce two workbooks.
        second_manager = build_users([synthetic_user("perf-organizer-secondary")])[0]
        self.fixture.program.managers.add(second_manager)
        export_tokens = [self.manager_token, str(AccessToken.for_user(second_manager))]
        if self.queued:
            export_route = self.endpoint("participant-export-jobs")
            export_clients = [
                (Operation(ACCEPT, self.request(export_route, token=token, payload={"query": {}})),)
                for token in export_tokens
            ]
        else:
            export_route = self.endpoint("management-participants-export")
            export_clients = [(Operation(EXCEL, self.request(export_route, token=token)),) for token in export_tokens]
        overview_clients = [(overview,) * 2] * 8
        participants_clients = [(participants,) * 2] * 8
        writers = self.writer_clients()
        self.run_phase("control_overview", overview_clients)
        self.run_phase("control_participants", participants_clients)
        self.run_phase("control_excel", export_clients)
        self.run_phase("mixed", overview_clients + participants_clients + writers + export_clients)
        self.run_phase("post_write", export_clients[:1], enrolled=set(self.enrollment_answers))
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

    def observe(self, operation):
        start = perf_counter()
        response = perf.fetch(operation.request, self.server_thread.port)
        return Observation(operation, response, start, perf_counter())

    def run_export(self, operation):
        attempt = ExportAttempt(perf_counter())

        def fetch(request_operation):
            row = self.observe(request_operation)
            attempt.observations.append(row)
            perf.require(not row.response.transport_error, row.response.transport_error)
            perf.require(
                row.response.status == EXPECTED_STATUS[request_operation.scenario], f"HTTP {row.response.status}"
            )
            return row

        def export_state(row):
            perf.require(row.response.content_type == "application/json", "Unexpected export JSON media type")
            data = json.loads(row.response.body)
            state = data["status"]
            perf.require(state in EXPORT_STATUSES, "Unexpected export job status")
            attempt.states.append(state)
            return UUID(data["id"]), state

        try:
            row = fetch(operation)
            if operation.scenario == EXCEL:
                attempt.workbook = row
                return attempt
            attempt.job_id, state = export_state(row)
            perf.require(state == "queued", "Export POST did not return queued status")
            url = f"{operation.request.path}{attempt.job_id}/"
            poll = Operation(POLL, self.request(url, token=operation.request.token))
            deadline = attempt.start + EXPORT_TIMEOUT_SECONDS
            while state == "queued":
                perf.require(perf_counter() < deadline, "Timed out waiting for queued export")
                sleep(POLL_INTERVAL_SECONDS)
                job_id, state = export_state(fetch(poll))
                perf.require(job_id == attempt.job_id, "Polling returned an unexpected export job")
            perf.require(state == "ready", f"Export reached {state} instead of ready")
            download = Operation(DOWNLOAD, self.request(url + "download/", token=operation.request.token))
            attempt.workbook = fetch(download)
        except Exception as error:
            attempt.error = perf.error_name(error)
        return attempt

    def run_phase(self, name, clients, *, enrolled=frozenset()):
        barrier = Barrier(len(clients), timeout=BARRIER_TIMEOUT_SECONDS)

        def run_client(operations):
            barrier.wait()
            if operations[0].scenario in {EXCEL, ACCEPT}:
                attempt = self.run_export(operations[0])
                return attempt.observations, attempt
            return [self.observe(operation) for operation in operations], None

        with ThreadPoolExecutor(max_workers=len(clients)) as executor:
            results = list(executor.map(run_client, clients))

        observations = [row for rows, _ in results for row in rows]
        first_requests = [rows[0] for rows, _ in results if rows]
        exports = [attempt for _, attempt in results if attempt is not None]
        start = min(row.start for row in observations)
        elapsed = max(row.end for row in observations) - start
        events = sorted(
            event for row in observations for event in ((row.start, 1), (row.end, -1))
        )
        groups = defaultdict(list)
        for row in observations:
            groups[row.operation.scenario].append(row)

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
                    "planned_samples": planned_samples.get(scenario),
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
            "initial_start_spread_ms": (max(row.start for row in first_requests) - start) * 1000,
            "wall_seconds": elapsed,
            "requests_per_second": len(observations) / elapsed,
            "scenarios": scenarios,
        }
        if exports:
            self.check_exports(phase, phase_errors, exports, write_rows, enrolled, groups[OVERVIEW], start)
        if write_rows:
            phase["native_enrollment_overlap"] = {}
            for scenario in (OVERVIEW, PARTICIPANTS, EXCEL, ACCEPT, SIGNUP):
                if not groups[scenario]:
                    continue
                overlaps = [overlap_seconds(row, write) for row in groups[scenario] for write in write_rows]
                phase["native_enrollment_overlap"][scenario] = {
                    "overlapping_pairs": sum(value > 0 for value in overlaps),
                    "longest_overlap_seconds": max(overlaps, default=0),
                }
                if scenario != SIGNUP and not any(overlaps):
                    phase_errors[f"No HTTP overlap between {scenario} and enrollment"] += 1
        phase.update(summarize(observations, phase_errors))
        self.report["phases"].append(phase)

    @staticmethod
    def enrollment_bounds(start, end, write_rows, enrolled):
        # A commit may precede its HTTP response. A read can see any subset of
        # overlapping enrollments plus all commits already acknowledged.
        required = enrolled | {
            write.operation.email
            for write in write_rows
            if write.response.status == EXPECTED_STATUS[ENROLLMENT] and write.end <= start
        }
        allowed = enrolled | {
            write.operation.email for write in write_rows if write.start < end
        }
        return required, allowed

    def validate_observation(self, row, write_rows, enrolled):
        scenario = row.operation.scenario
        response = row.response
        if response.transport_error:
            return response.transport_error
        if response.status != EXPECTED_STATUS[scenario]:
            return f"HTTP {response.status}"
        if scenario in {EXCEL, ACCEPT, POLL, DOWNLOAD}:
            return None
        required, allowed = self.enrollment_bounds(row.start, row.end, write_rows, enrolled)
        return perf.validated(
            response,
            perf.json_response(lambda data: self.check_json(row.operation, data, required, allowed)),
        )

    def check_exports(self, phase, errors, exports, write_rows, enrolled, overview_rows, phase_start):
        jobs = {}
        if self.queued:
            job_ids = {attempt.job_id for attempt in exports if attempt.job_id is not None}
            jobs = ParticipantExportJob.objects.only("status", "started_at", "completed_at").in_bulk(job_ids)
        if self.queued and len(jobs) != len(exports):
            errors["Expected a distinct persisted job for each export attempt"] += 1
        if write_rows:
            new_profiles = PartnerProgramUserProfile.objects.filter(
                partner_program=self.fixture.program,
                user__email__in=self.enrollment_answers,
            ).select_related("user")
            self.expected_participants.update(self.participant_values(new_profiles))
        export_started = min(attempt.start for attempt in exports)
        windows = []
        files = []
        report = phase["exports"] = {
            "planned_files": len(exports),
            "files": files,
            "validation_after_http_traffic": True,
        }
        for attempt in exports:
            result = {
                "observed_states": attempt.states,
                "job_id": str(attempt.job_id) if attempt.job_id else None,
                "error": attempt.error,
            }
            files.append(result)
            if self.queued and attempt.observations:
                result["acceptance_ms"] = attempt.observations[0].response.elapsed_ms
            if attempt.error:
                errors[attempt.error] += 1
                continue
            workbook = attempt.workbook
            result["through_download_seconds"] = workbook.end - attempt.start
            result["download_bytes"] = len(workbook.response.body)
            job = jobs.get(attempt.job_id)
            if self.queued:
                if not (job and job.status == "ready" and job.started_at and job.completed_at):
                    result["error"] = "Missing worker interval on the ready export job"
                    errors[result["error"]] += 1
                    continue
                start = job.started_at.timestamp() - self.clock_offset
                end = job.completed_at.timestamp() - self.clock_offset
                if not attempt.start <= start < end <= workbook.end:
                    result["error"] = "Export worker interval outside the client request window"
                    errors[result["error"]] += 1
                    continue
            else:
                start, end = workbook.start, workbook.end

            window = ExportWindow(start, end)
            windows.append(window)
            result["export_window_seconds"] = {"start": start - phase_start, "end": end - phase_start}
            result["overview_overlap_count"] = sum(overlap_seconds(window, row) > 0 for row in overview_rows)
            result["enrollment_overlap_count"] = sum(overlap_seconds(window, row) > 0 for row in write_rows)
            required, allowed = self.enrollment_bounds(start, end, write_rows, enrolled)
            validation_started = perf_counter()
            try:
                result["verified_rows"] = self.check_snapshot_workbook(workbook.response, required, allowed)
            except Exception as error:
                result["error"] = perf.error_name(error)
                errors[result["error"]] += 1
            validation_ended = perf_counter()
            result["validation_seconds"] = validation_ended - validation_started
            result["through_validation_seconds"] = validation_ended - attempt.start

        downloaded = [attempt.workbook.end for attempt in exports if attempt.workbook is not None]
        verified = sum("verified_rows" in result for result in files)
        report["verified_files"] = verified
        report["all_downloaded_seconds"] = (
            max(downloaded) - export_started if len(downloaded) == len(exports) else None
        )
        report["all_validated_seconds"] = perf_counter() - export_started if verified == len(exports) else None
        report["window_kind"] = "worker_started_to_completed" if self.queued else "sync_http"
        events = sorted(event for window in windows for event in ((window.start, 1), (window.end, -1)))
        report["peak_overlapping_export_windows"] = max(accumulate(delta for _, delta in events), default=0)
        report["overview_requests_overlapping_export"] = sum(
            any(overlap_seconds(row, window) for window in windows) for row in overview_rows
        )
        if self.queued and report["peak_overlapping_export_windows"] > 1:
            errors["Multiple background workbook writers overlapped"] += 1
        if overview_rows and not report["overview_requests_overlapping_export"]:
            errors["No overlap between Overview requests and export windows"] += 1

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

    @staticmethod
    def participant_values(profiles):
        return {
            profile.user.email: (
                " ".join(filter(None, (profile.user.first_name, profile.user.last_name, profile.user.patronymic))),
                profile.registration_region or profile.user.city or profile.user.region or "—",
                profile.datetime_created,
                profile.user.last_activity,
            )
            for profile in profiles
        }

    @staticmethod
    def check_excel_date(actual, expected):
        if expected is None:
            perf.require(actual == "—", "Missing XLSX date placeholder")
        else:
            local = expected.astimezone(MOSCOW).replace(tzinfo=None)
            perf.require(isinstance(actual, datetime), "Excel date is not a datetime cell")
            perf.require(abs(actual - local) <= timedelta(milliseconds=1), "Incorrect Moscow Excel date")

    def check_snapshot_workbook(self, response, required, allowed):
        perf.check_xlsx_headers(response)
        workbook = load_workbook(BytesIO(response.body), read_only=True)
        try:
            perf.require(workbook.sheetnames == ["Участники", "Анкеты"], "Unexpected XLSX sheets")
            participants = workbook["Участники"].values
            answers = workbook["Анкеты"].values
            perf.require(
                next(participants) == (
                    "№", "Участник", "Почта", "Регион", "Дата регистрации (МСК)", "Последняя активность (МСК)"
                ),
                "Unexpected XLSX participant header",
            )
            perf.require(
                next(answers) == ("Участник", "Почта", "Поле анкеты", "Ответ"),
                "Unexpected XLSX answer header",
            )
            emails = Counter()
            for expected_number, row in enumerate(participants, start=1):
                number, name, email, region, registered, active = row
                perf.require(isinstance(number, int) and number == expected_number, "Incorrect XLSX row number")
                perf.require(email in self.expected_participants, "Unknown XLSX participant")
                expected_name, expected_region, expected_registered, expected_active = self.expected_participants[email]
                perf.require((name, region) == (expected_name, expected_region), "Incorrect XLSX participant details")
                self.check_excel_date(registered, expected_registered)
                self.check_excel_date(active, expected_active)
                emails[email] += 1

            seeded_answers = self.fixture.answers_by_email
            new_emails = emails.keys() - seeded_answers.keys()
            perf.require(required <= new_emails <= allowed, "XLSX snapshot outside enrollment bounds")
            expected = {**seeded_answers, **{email: self.enrollment_answers[email] for email in new_emails}}
            perf.require(emails == Counter(expected.keys()), "XLSX lost or duplicated a participant")
            answer_rows = Counter(tuple(row) for row in answers)
            perf.require(
                answer_rows == Counter(
                    (self.expected_participants[email][0], email, *answer) for email, answer in expected.items()
                ),
                "XLSX changed a saved answer, historical field label or participant name",
            )
            return {"participants": sum(emails.values()), "answers": sum(answer_rows.values())}
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

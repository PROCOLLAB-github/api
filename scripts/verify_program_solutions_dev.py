"""Приемка API на dev; новые записи всегда откатываются транзакцией."""


def stable_json_value(value):
    if isinstance(value, (memoryview, bytes, bytearray)):
        return {"binary_hex": bytes(value).hex()}
    return str(value)


def main():
    import hashlib
    import io
    import json
    import os
    import sys
    from unittest.mock import patch
    from uuid import uuid4

    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
    import django

    django.setup()
    from django.apps import apps
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection, transaction
    from django.db.migrations.executor import MigrationExecutor
    from django.test import override_settings
    from django.utils import timezone
    from rest_framework.test import APIClient
    from partner_programs.models import PartnerProgram, PartnerProgramField
    from partner_programs.solution_models import ProgramSolution
    from partner_programs.tests.helpers import (
        create_user, create_partner_program, create_program_member,
        create_program_project, create_project,
    )
    from project_rates.tests.helpers import create_rate_expert, create_rate_criteria
    from project_rates.criteria_policy import revision

    assert connection.vendor == "postgresql"
    assert (
        __import__("re").fullmatch(r"[0-9a-f]{40}", os.environ.get("VERIFY_EXPECTED_API_SHA", ""))
        or os.environ.get("DJANGO_SETTINGS_MODULE") == "procollab.settings_ci"
    )
    assert not MigrationExecutor(connection).migration_plan(
        MigrationExecutor(connection).loader.graph.leaf_nodes()
    )
    prefix = "postmerge-dev-20261026-" + uuid4().hex[:12]
    checks, wire, programs = [], [], []

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, default=stable_json_value).encode()
        ).hexdigest()

    models = [
        model
        for model in apps.get_models(include_auto_created=True)
        if model._meta.app_label in {"partner_programs", "projects", "project_rates"}
        and not model._meta.proxy
    ]

    baseline_ids = {
        model._meta.label: list(model._base_manager.order_by("pk").values_list("pk", flat=True))
        for model in models
    }

    def retained():
        result = {}
        for model in models:
            rows = list(
                model._base_manager.filter(pk__in=baseline_ids[model._meta.label]).order_by("pk").values()
            )
            result[model._meta.label] = {"count": len(rows), "hash": digest(rows)}
        return result

    baseline = retained()
    legacy_ids = [
        int(value) for value in os.environ.get("VERIFY_EXPECTED_LEGACY_IDS", "").split(",") if value
    ]
    if legacy_ids:
        assert list(
            PartnerProgram.objects.filter(pk__in=legacy_ids, solution_storage_mode="legacy_project")
            .order_by("pk")
            .values_list("pk", flat=True)
        ) == sorted(legacy_ids)
    legacy_before = list(
        PartnerProgram.objects.filter(solution_storage_mode="legacy_project")
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    project_count = apps.get_model("projects.Project").objects.count()
    rollback_complete = False

    def request(actor, method, path, body=None, expected=200, binary=False):
        client = APIClient()
        if actor is not None:
            client.force_authenticate(actor)
        response = getattr(client, method)(
            path, {} if body is None else body, format="json", secure=True, HTTP_HOST="dev.procollab.ru"
        )
        wire.append({"method": method.upper(), "path": path, "status": response.status_code})
        assert response.status_code == expected, (
            method,
            path,
            response.status_code,
            getattr(response, "data", None),
        )
        return response.content if binary else response.data

    try:
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            ALLOWED_HOSTS=["testserver", "dev.procollab.ru"],
            CACHES={
                "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": prefix}
            },
            CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
        ), patch("celery.app.task.Task.apply_async"), patch("core.log.middleware._add_logger_handler"):
            with transaction.atomic():
                users = {
                    role: (create_rate_expert if role == "expert" else create_user)(
                        prefix=prefix + "-" + role
                    )
                    for role in ["manager", "captain", "member", "pending", "outsider", "expert"]
                }
                get_user_model().objects.filter(pk__in=[user.pk for user in users.values()]).update(
                    is_active=True
                )
                now = timezone.now()
                for template, competitive in [
                    ("case_championship", True),
                    ("hackathon", True),
                    ("hackathon", False),
                ]:
                    program = create_partner_program(
                        name=prefix,
                        tag=prefix + "-" + template + str(competitive),
                        solution_storage_mode="solution",
                        solution_template=template,
                        solution_creation_enabled=False,
                        is_competitive=competitive,
                        is_distributed_evaluation=competitive,
                        required_evaluators=1 if competitive else None,
                        max_project_rates=3,
                        legacy_team_min_size=2,
                        legacy_team_max_size=4,
                        datetime_project_submission_ends=now + timezone.timedelta(days=2),
                        datetime_evaluation_ends=now + timezone.timedelta(days=3),
                        datetime_finished=now + timezone.timedelta(days=4),
                        publish_projects_after_finish=True,
                    )
                    program.managers.add(users["manager"])
                    users["expert"].expert.programs.add(program)
                    for role in ["captain", "member", "pending"]:
                        create_program_member(
                            program, user=users[role], data={"private_note": "private-registration"}
                        )
                    fields = {}
                    definitions = [
                        ("case", "select", "case"),
                        ("materials", "textarea", "other"),
                        ("zero", "number", "other"),
                        ("boolean", "checkbox", "other"),
                    ]
                    if template == "hackathon":
                        definitions.append(("repository", "url", "repository"))
                    for position, (name, kind, purpose) in enumerate(definitions):
                        fields[name] = PartnerProgramField.objects.create(
                            partner_program=program,
                            name=name,
                            label=name,
                            field_type=kind,
                            purpose=purpose,
                            position=position,
                            is_required=True,
                            show_filter=name == "case",
                            solution_options=["Case A", "Case B"] if name == "case" else [],
                        ).pk
                    if competitive:
                        create_rate_criteria(program, name="Quality", type="int", min_value=0, max_value=10)
                        create_rate_criteria(program, name="Verified", type="bool")
                    base = f"/programs/{program.pk}/"
                    blocked = request(users["captain"], "post", base + "solutions/", {}, 409)
                    assert blocked["code"] == "solution_creation_disabled"
                    call_command(
                        "set_solution_creation",
                        program_id=program.pk,
                        enable=True,
                        apply=True,
                        stdout=io.StringIO(),
                    )
                    solution = request(
                        users["captain"], "post", base + "solutions/", {"name": "Postmerge acceptance"}, 201
                    )
                    root = base + f"solutions/{solution['id']}/"
                    invite = request(
                        users["captain"],
                        "post",
                        root + "invitations/",
                        {
                            "expected_solution_version": solution["version"],
                            "recipient_user_id": users["member"].pk,
                            "role": "Analyst",
                        },
                        201,
                    )["invitation"]
                    request(
                        users["member"],
                        "post",
                        f"/solution-invitations/{invite['id']}/accept/",
                        {"expected_version": invite["version"]},
                    )
                    solution = request(users["captain"], "get", root)
                    request(
                        users["captain"],
                        "post",
                        root + "invitations/",
                        {
                            "expected_solution_version": solution["version"],
                            "recipient_user_id": users["pending"].pk,
                            "role": "Designer",
                        },
                        201,
                    )
                    solution = request(users["captain"], "get", root)
                    assert solution["team"]["accepted_count"] == 2 and solution["team"]["pending_count"] == 1
                    answers = [
                        {"field_id": fields[name], "value": value}
                        for name, value in [
                            ("case", "Case A"),
                            ("materials", "Actual merged dev runtime"),
                            ("zero", 0),
                            ("boolean", False),
                        ]
                    ]
                    if "repository" in fields:
                        answers.append(
                            {"field_id": fields["repository"], "value": "https://example.org/postmerge"}
                        )
                    solution = request(
                        users["captain"],
                        "patch",
                        root,
                        {
                            "expected_version": solution["version"],
                            "expected_form_revision": solution["form"]["revision"],
                            "answers": answers,
                        },
                    )
                    request(users["outsider"], "get", root, expected=404)
                    request(
                        users["member"],
                        "patch",
                        root,
                        {
                            "expected_version": solution["version"],
                            "expected_form_revision": solution["form"]["revision"],
                            "name": "Forbidden",
                        },
                        403,
                    )
                    if competitive:
                        solution = request(
                            users["captain"],
                            "post",
                            root + "submit/",
                            {
                                "expected_version": solution["version"],
                                "expected_form_revision": solution["form"]["revision"],
                            },
                        )
                        assert (
                            solution["submission"]["status"] == "submitted"
                            and solution["form"]["is_snapshot"]
                            and not solution["permissions"]["can_edit"]
                        )
                        stored = ProgramSolution.objects.get(pk=solution["id"])
                        assert len(stored.submission_snapshot["members"]) == 2
                        options_url = (
                            base
                            + f"management/solution-evaluation/experts/{users['expert'].expert.pk}/assignments/"
                        )
                        options = request(users["manager"], "get", options_url)
                        request(
                            users["manager"],
                            "put",
                            options_url,
                            {"revision": options["revision"], "solution_ids": [solution["id"]]},
                        )
                        scores = [
                            {
                                "criterion_id": criterion.pk,
                                "value": "0"
                                if criterion.type == "int"
                                else "False"
                                if criterion.type == "bool"
                                else "",
                            }
                            for criterion in program.criterias.all()
                        ]
                        rated = request(
                            users["expert"],
                            "post",
                            root + "evaluation/",
                            {"expected_criteria_revision": revision(program), "scores": scores},
                        )
                        assert rated["is_completed"]
                        result = request(users["manager"], "get", base + "management/solution-results/")
                        entry = next(
                            row
                            for group in result["groups"]
                            for row in group["solutions"]
                            if row["solution_id"] == solution["id"]
                        )
                        assert (
                            entry["score"] == 0 and entry["completed"] == 1 and entry["evaluation_complete"]
                        )
                        checks.append(template + ":submit-snapshot-assignment-zero-false-results")
                    overview = request(users["manager"], "get", base + "management/solution-analytics/")
                    assert overview["summary"]["solutions"]["total"] == 1
                    export = request(
                        users["manager"],
                        "get",
                        base + "management/solution-analytics/export/?kind=solutions",
                        binary=True,
                    )
                    assert export.startswith(b"PK")
                    assert request(None, "get", base + "published-solutions/")["count"] == 0
                    assert ProgramSolution.objects.get(pk=solution["id"]).published_at is None
                    PartnerProgram.objects.filter(pk=program.pk, tag__startswith=prefix).update(
                        datetime_finished=now - timezone.timedelta(seconds=1)
                    )
                    public = request(None, "get", base + f"published-solutions/{solution['id']}/")
                    assert ProgramSolution.objects.get(pk=solution["id"]).published_at is not None
                    assert public["team"]["accepted_count"] == 2
                    public_keys = json.dumps(public, default=str)
                    assert all(
                        word not in public_keys
                        for word in ["private-registration", "pending_count", '"scores"', '"criteria"']
                    )
                    for expected_answer in answers:
                        assert expected_answer in public["answers"] or any(
                            row["field_id"] == expected_answer["field_id"]
                            and row["value"] == expected_answer["value"]
                            for row in public["answers"]
                        )
                    call_command(
                        "set_solution_creation",
                        program_id=program.pk,
                        disable=True,
                        apply=True,
                        stdout=io.StringIO(),
                    )
                    request(users["pending"], "post", base + "solutions/", {}, 409)
                    request(users["captain"], "get", root)
                    checks.append(
                        template
                        + (":competitive" if competitive else ":noncompetitive")
                        + ":create-team-save-permissions-analytics-xlsx-immediate-publication-without-job-creation-stop"
                    )
                    programs.append(
                        {"template": template, "competitive": competitive, "transientProgramId": program.pk}
                    )
                assert apps.get_model("projects.Project").objects.count() == project_count
                legacy = create_partner_program(
                    name=prefix, tag=prefix + "-legacy-immediate",
                    publish_projects_after_finish=True,
                    datetime_finished=now + timezone.timedelta(days=1),
                )
                work = create_project(is_public=False)
                create_program_project(legacy, project=work)
                before_work = apps.get_model("projects.Project").objects.filter(pk=work.pk).values().get()
                path = f"/programs/{legacy.pk}/published-projects/"
                request(None, "get", path, expected=404)
                PartnerProgram.objects.filter(pk=legacy.pk, tag__startswith=prefix).update(
                    datetime_finished=now - timezone.timedelta(seconds=1)
                )
                page = request(None, "get", path)
                assert page["count"] == 1 and page["results"][0]["id"] == work.pk
                after_work = apps.get_model("projects.Project").objects.filter(pk=work.pk).values().get()
                assert after_work == dict(before_work, is_public=True)
                request(None, "get", f"/projects/{work.pk}/")
                checks.append("legacy-immediate-publication-without-job-only-is-public-changed")
                for old in PartnerProgram.objects.filter(pk__in=legacy_before).order_by("pk"):
                    request(None, "get", f"/programs/{old.pk}/", expected=404 if old.draft else 200)
                    manager = old.managers.first()
                    if manager is not None:
                        request(manager, "get", f"/programs/{old.pk}/management/projects/")
                checks.append("all-existing-legacy-programs-detail-and-manager-projects")
                transaction.set_rollback(True)
            assert not PartnerProgram.objects.filter(tag__startswith=prefix).exists()
            assert not get_user_model().objects.filter(email__startswith=prefix).exists()
            rollback_complete = True
    finally:
        after = retained()
        changed = {
            label: {"before": baseline[label], "after": after[label]}
            for label in baseline
            if baseline[label] != after[label]
        }
        if changed:
            sys.stdout.write("RETENTION_DIFF=" + json.dumps(changed, sort_keys=True) + "\n")
        assert (
            after == baseline
        ), "Existing model data changed; inspect concurrent writers before attributing any difference."
        assert (
            list(
                PartnerProgram.objects.filter(pk__in=legacy_before, solution_storage_mode="legacy_project")
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            == legacy_before
        )

    assert rollback_complete
    sys.stdout.write(
        "POSTMERGE_DEV_EVIDENCE="
        + json.dumps(
            {
                "complete": True,
                "expectedApiMerge": os.environ.get("VERIFY_EXPECTED_API_SHA"),
                "scope": (
                    "APIClient in actual dev web container"
                    if os.environ.get("VERIFY_EXPECTED_API_SHA")
                    else "local PostgreSQL preflight"
                )
                + ", transaction rolled back",
                "checks": checks,
                "programs": programs,
                "http": wire,
                "legacyPrograms": len(legacy_before),
                "premergePublicIdsRemainLegacy": legacy_ids,
                "protectedModelHashes": baseline,
                "retainedDigest": digest(baseline),
                "legacyDataUnchanged": True,
                "newProjectCount": 0,
                "allSyntheticRowsRolledBack": True,
                "externalMailAndTasksSuppressed": True,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

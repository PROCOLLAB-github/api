"""DEV acceptance: every existing program, only intended publication marker writes.

Unlike the synthetic rollback acceptance, successful publication is committed.
Every business row and all non-publication fields must remain exactly unchanged.
No emails, registrations, submissions, program edits or fixture creation.
"""

import hashlib
import json
import os
import re
import sys
from unittest.mock import patch


def main():
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
    import django

    django.setup()
    from django.apps import apps
    from django.db import connection, transaction
    from django.test import override_settings
    from django.utils import timezone
    from rest_framework.test import APIClient

    from partner_programs.models import PartnerProgram, PartnerProgramUserProfile
    from partner_programs.solution_models import ProgramSolution
    from partner_programs.services.publishing import legacy_program_projects
    from projects.models import Project

    assert connection.vendor == "postgresql"
    assert re.fullmatch(r"[0-9a-f]{40}", os.environ.get("VERIFY_EXPECTED_API_SHA", ""))
    assert os.environ.get("VERIFY_PHASE") == "verify_publication"
    now = timezone.now()
    models = [
        model for model in apps.get_models(include_auto_created=True)
        if model._meta.app_label in {"partner_programs", "projects", "project_rates"}
        and not model._meta.proxy
    ]

    def stable_value(value):
        if isinstance(value, (memoryview, bytes, bytearray)):
            return {"binary_hex": bytes(value).hex()}
        return str(value)

    def snapshot():
        hashes = {}
        for model in models:
            fields = [field.attname for field in model._meta.concrete_fields]
            if model is Project:
                fields.remove("is_public")
            if model is ProgramSolution:
                fields.remove("published_at")
            rows = list(model._base_manager.order_by("pk").values(*fields))
            payload = json.dumps(rows, sort_keys=True, default=stable_value).encode()
            hashes[model._meta.label] = dict(count=len(rows), hash=hashlib.sha256(payload).hexdigest())
        return hashes

    def linked_projects(program):
        from django.db.models import Q

        return Project.objects.filter(
            Q(program_links__partner_program=program)
            | Q(pk__in=PartnerProgramUserProfile.objects.filter(
                partner_program=program,
            ).values("project_id")),
            draft=False,
        ).distinct()

    client = APIClient()
    requests, results = [], []

    def read(path, expected=200):
        response = client.get(path, secure=True, HTTP_HOST="dev.procollab.ru")
        requests.append(dict(path=path, status=response.status_code))
        assert response.status_code == expected, (path, response.status_code, expected)
        return getattr(response, "data", None)

    def all_ids(path, kind):
        ids, offset, expected_count = [], 0, None
        while True:
            page = read(f"{path}?limit=100&offset={offset}")
            if expected_count is None:
                expected_count = page["count"]
            assert expected_count == page["count"]
            rows = page["results"]
            ids.extend(row["id"] if kind == "project" else row["application"]["solution_id"] for row in rows)
            offset += len(rows)
            if offset >= expected_count:
                break
            assert rows, (path, "pagination did not advance")
        assert len(ids) == len(set(ids)) == expected_count
        return sorted(ids)

    with override_settings(
        ALLOWED_HOSTS=["dev.procollab.ru", "testserver"],
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    ), patch("django.utils.timezone.now", return_value=now), patch("core.log.middleware._add_logger_handler"):
        with transaction.atomic():
            before = snapshot()
            projects_before = dict(Project.objects.values_list("pk", "is_public"))
            solutions_before = dict(ProgramSolution.all_objects.values_list("pk", "published_at"))
            expected_projects, expected_solutions = projects_before.copy(), solutions_before.copy()
            programs = list(PartnerProgram.objects.order_by("pk"))
            for program in programs:
                due = bool(
                    not program.draft and program.publish_projects_after_finish
                    and program.datetime_finished <= now
                )
                if due and program.solution_storage_mode == "legacy_project":
                    for pk in legacy_program_projects(program.pk).values_list("pk", flat=True):
                        expected_projects[pk] = True
                elif due and program.solution_storage_mode == "solution":
                    rows = ProgramSolution.objects.filter(program=program, published_at__isnull=True)
                    if program.is_competitive:
                        rows = rows.filter(status="submitted")
                    for pk in rows.values_list("pk", flat=True):
                        expected_solutions[pk] = now

            for program in programs:
                root = f"/programs/{program.pk}/"
                due = bool(
                    not program.draft and program.publish_projects_after_finish
                    and program.datetime_finished <= now
                )
                # The ordinary program page must be sufficient; no task/service call here.
                read(root)
                if program.solution_storage_mode == "legacy_project":
                    path = root + "published-projects/"
                    if due:
                        actual = all_ids(path, "project")
                        expected = sorted(linked_projects(program).filter(is_public=True).values_list("pk", flat=True))
                        assert actual == expected, (program.pk, actual, expected)
                        for pk in actual:
                            read(f"/projects/{pk}/")
                    else:
                        read(path, 404)
                        actual = []
                    read(root + "published-solutions/", 404)
                else:
                    path = root + "published-solutions/"
                    read(root + "published-projects/", 404)
                    if program.draft:
                        read(path, 404)
                        actual = []
                    else:
                        actual = all_ids(path, "solution")
                        rows = ProgramSolution.objects.filter(program=program, published_at__isnull=False)
                        if program.is_competitive:
                            rows = rows.filter(status="submitted")
                        assert actual == sorted(rows.values_list("pk", flat=True)), program.pk
                        for pk in actual:
                            material = read(path + f"{pk}/")
                            assert set(material) == {"application", "published_at", "fields", "answers", "team"}
                            assert material["application"]["program_id"] == program.pk
                            assert material["application"]["solution_id"] == pk
                read(root + "projects/", 401)
                results.append(dict(
                    program_id=program.pk, mode=program.solution_storage_mode,
                    draft=program.draft, publication_enabled=program.publish_projects_after_finish,
                    finished=program.datetime_finished <= now, published_count=len(actual),
                ))

            assert dict(Project.objects.values_list("pk", "is_public")) == expected_projects
            assert dict(ProgramSolution.all_objects.values_list("pk", "published_at")) == expected_solutions
            after = snapshot()
            assert after == before, "Non-publication data changed"
            # Repeat every program request; original publication timestamps must survive.
            for program in programs:
                read(f"/programs/{program.pk}/")
            assert dict(Project.objects.values_list("pk", "is_public")) == expected_projects
            assert dict(ProgramSolution.all_objects.values_list("pk", "published_at")) == expected_solutions
            assert snapshot() == before

    print("PROGRAM_PUBLICATION_ACCEPTANCE=" + json.dumps(dict(  # noqa: T201
        source_sha=os.environ["VERIFY_EXPECTED_API_SHA"], checked_at=now.isoformat(),
        programs=results, requests=requests, retained_models=before,
        published_project_ids=[pk for pk in expected_projects if expected_projects[pk] != projects_before[pk]],
        published_solution_ids=[pk for pk in expected_solutions if expected_solutions[pk] != solutions_before[pk]],
        non_publication_data_unchanged=after == before, repeat_requests_idempotent=True,
    ), sort_keys=True))


if __name__ == "__main__":
    main()

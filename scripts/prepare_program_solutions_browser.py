"""Создает только собственные QA-программы; завершение отключает новое создание."""
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch


def stable_json_value(value):
    if isinstance(value, (memoryview, bytes, bytearray)):
        return {"binary_hex": bytes(value).hex()}
    return str(value)


def main():
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
    import django

    django.setup()
    from django.apps import apps
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import transaction
    from django.test import override_settings
    from django.utils import timezone
    from partner_programs.models import PartnerProgram, PartnerProgramField
    from partner_programs.solution_models import ProgramSolution
    from partner_programs.services.publishing import publish_solution_program
    from partner_programs.tests.helpers import create_partner_program, create_program_member

    key = os.environ["VERIFY_FIXTURE_KEY"]
    assert re.fullmatch(r"[a-z0-9-]{8,50}", key)
    manager_id = int(os.environ["VERIFY_MANAGER_ID"])
    assert manager_id > 0
    phase = os.environ["VERIFY_PHASE"]
    assert phase in ("prepare_browser", "finalize_browser")
    prefix = "qa-solution-browser-" + key
    receipt = Path("/procollab/log") / (prefix + ".json")
    if os.environ.get("DJANGO_SETTINGS_MODULE") == "procollab.settings_ci":
        receipt = Path(os.environ["TEMP"]) / (prefix + ".json")
    manager = get_user_model().objects.get(pk=manager_id, is_active=True)

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, default=stable_json_value).encode()
        ).hexdigest()

    def rows(model, ids):
        return list(model._base_manager.filter(pk__in=ids).order_by("pk").values())

    protected_models = [
        model
        for model in apps.get_models(include_auto_created=True)
        if model._meta.app_label in {"partner_programs", "projects", "project_rates"}
        and not model._meta.proxy
    ]
    with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"), patch(
        "celery.app.task.Task.apply_async"
    ):
        if phase == "prepare_browser":
            assert not receipt.exists(), "Use a fresh fixture key; preparation must not be replayed."
            assert not PartnerProgram.objects.filter(tag__startswith=prefix).exists()
            baseline = {}
            baseline_values = {}
            for model in protected_models:
                ids = list(model._base_manager.order_by("pk").values_list("pk", flat=True))
                baseline_values[model._meta.label] = rows(model, ids)
                baseline[model._meta.label] = {"ids": ids, "hash": digest(baseline_values[model._meta.label])}
            result = {
                "prefix": prefix,
                "managerId": manager_id,
                "programs": [],
                "baseline": baseline,
                "projectCount": apps.get_model("projects.Project").objects.count(),
                "complete": False,
            }
            with transaction.atomic():
                for template, competitive, label in [
                    ("case_championship", True, "Кейс-чемпионат"),
                    ("hackathon", True, "Хакатон"),
                    ("hackathon", False, "Неконкурсная программа"),
                ]:
                    now = timezone.now()
                    program = create_partner_program(
                        name="[QA 26.10] " + label + " — решения",
                        tag=prefix + "-" + str(len(result["programs"]) + 1),
                        description="Отдельная программа приемки решений после merge. Старые программы не изменяются.",
                        solution_storage_mode="solution",
                        solution_template=template,
                        solution_creation_enabled=False,
                        is_competitive=competitive,
                        legacy_team_min_size=1,
                        legacy_team_max_size=4,
                        datetime_registration_ends=now + timezone.timedelta(days=7),
                        datetime_project_submission_ends=now + timezone.timedelta(days=7),
                        datetime_evaluation_ends=now + timezone.timedelta(days=8),
                        datetime_finished=now + timezone.timedelta(days=9),
                        publish_projects_after_finish=True,
                    )
                    program.managers.add(manager)
                    create_program_member(program, user=manager)
                    fields = {}
                    definitions = [
                        ("case", "select", "Кейс", "case"),
                        ("materials", "textarea", "Описание решения", "other"),
                        ("zero", "number", "Число для проверки", "other"),
                        ("boolean", "checkbox", "Дополнительная опция", "other"),
                    ]
                    if template == "hackathon":
                        definitions.append(("repository", "url", "Ссылка на репозиторий", "repository"))
                    for position, (name, kind, field_label, purpose) in enumerate(definitions):
                        fields[name] = PartnerProgramField.objects.create(
                            partner_program=program,
                            name=name,
                            label=field_label,
                            field_type=kind,
                            purpose=purpose,
                            position=position,
                            is_required=True,
                            show_filter=name == "case",
                            solution_options=["Город", "Образование"] if name == "case" else [],
                        ).pk
                    call_command(
                        "set_solution_creation",
                        program_id=program.pk,
                        enable=True,
                        apply=True,
                        stdout=io.StringIO(),
                    )
                    result["programs"].append(
                        {"id": program.pk, "template": template, "competitive": competitive, "fields": fields}
                    )
                for model in protected_models:
                    entry = baseline[model._meta.label]
                    current = rows(model, entry["ids"])
                    if digest(current) != entry["hash"]:
                        pk_name = model._meta.pk.attname
                        old_rows = {row[pk_name]: row for row in baseline_values[model._meta.label]}
                        changed_fields = sorted(
                            {
                                name
                                for row in current
                                for name in row
                                if old_rows[row[pk_name]].get(name) != row[name]
                            }
                        )
                        sys.stdout.write(
                            "PREPARE_RETENTION_DIFF="
                            + json.dumps(
                                {
                                    "model": model._meta.label,
                                    "fields": changed_fields,
                                    "beforeCount": len(old_rows),
                                    "afterCount": len(current),
                                }
                            )
                            + "\n"
                        )
                        raise AssertionError(model._meta.label)
            receipt.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf8")
            receipt.chmod(0o600)
            sys.stdout.write(
                "BROWSER_FIXTURES="
                + json.dumps(
                    {
                        "managerId": manager_id,
                        "key": key,
                        "programs": result["programs"],
                        "oldModelsUnchanged": len(baseline),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        else:
            assert receipt.exists(), "Preparation receipt missing."
            result = json.loads(receipt.read_text(encoding="utf8"))
            assert result["prefix"] == prefix and result["managerId"] == manager_id
            assert not result["complete"], "Finalization must not be replayed."
            completed = []
            with transaction.atomic():
                for item in result["programs"]:
                    program = PartnerProgram.objects.get(
                        pk=item["id"], tag__startswith=prefix, solution_storage_mode="solution"
                    )
                    assert program.managers.filter(pk=manager_id).exists()
                    solution = ProgramSolution.objects.get(program=program, captain_id=manager_id)
                    assert solution.answers.count() >= 4
                    assert solution.status == ("submitted" if item["competitive"] else "draft")
                    values = {answer.field_id: answer.value for answer in solution.answers.all()}
                    assert values[item["fields"]["zero"]] == 0 and values[item["fields"]["boolean"]] is False
                    if item["competitive"]:
                        assert len(solution.submission_snapshot["members"]) == 1
                    call_command(
                        "set_solution_creation",
                        program_id=program.pk,
                        disable=True,
                        apply=True,
                        stdout=io.StringIO(),
                    )
                    PartnerProgram.objects.filter(pk=program.pk, tag__startswith=prefix).update(
                        datetime_finished=timezone.now() - timezone.timedelta(seconds=1)
                    )
                    assert publish_solution_program(program.pk, now=timezone.now()) == 1
                    solution.refresh_from_db()
                    assert solution.published_at is not None
                    completed.append(
                        {
                            **item,
                            "solutionId": solution.pk,
                            "published": True,
                            "creationEnabled": False,
                            "status": solution.status,
                        }
                    )
                for model in protected_models:
                    entry = result["baseline"][model._meta.label]
                    assert digest(rows(model, entry["ids"])) == entry["hash"], model._meta.label
                assert apps.get_model("projects.Project").objects.count() == result["projectCount"]
                result["complete"] = True
                result["completedPrograms"] = completed
            receipt.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf8")
            receipt.chmod(0o600)
            sys.stdout.write(
                "BROWSER_ACCEPTANCE="
                + json.dumps(
                    {
                        "complete": True,
                        "key": key,
                        "programs": completed,
                        "oldModelsUnchanged": len(result["baseline"]),
                        "newProjects": 0,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()

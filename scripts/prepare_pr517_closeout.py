"""Bounded DEV-only fixtures for PR517 browser acceptance; existing rows are immutable."""

import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path


def _stable(value):
    if isinstance(value, (memoryview, bytes, bytearray)):
        return {"binary_hex": bytes(value).hex()}
    return str(value)


def _digest(model, ids):
    digest = hashlib.sha256()
    for row in model._base_manager.filter(pk__in=ids).order_by("pk").values().iterator():
        digest.update(json.dumps(row, sort_keys=True, default=_stable).encode())
    return digest.hexdigest()


def prepare(
    key, manager_id, captain_ids, expert_user_ids, participant_id, *, apply=False
):
    from django.apps import apps
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import transaction
    from django.utils import timezone

    from partner_programs.constants import PROGRAM_CASE_FIELD_NAME
    from partner_programs.models import (
        PartnerProgram,
        PartnerProgramField,
        PartnerProgramFieldValue,
        PartnerProgramProject,
        PartnerProgramUserProfile,
    )
    from partner_programs.solution_answers import update_solution
    from partner_programs.solution_api import create_solution
    from partner_programs.solution_schema import form_data
    from partner_programs.solution_submission import submit_solution
    from project_rates.models import Criteria
    from projects.models import Project
    from users.models import Expert

    if not re.fullmatch(r"[a-z0-9-]{8,35}", key):
        raise ValueError("Invalid PR517 fixture key")
    if len(captain_ids) != 3 or len(set(captain_ids)) != 3:
        raise ValueError("Exactly three existing test captains are required")
    prefix = "pr517-closeout-" + key
    User = get_user_model()
    required = {manager_id, participant_id, *captain_ids, *expert_user_ids}
    users = User.objects.in_bulk(required)
    if set(users) != required or any(not user.is_active for user in users.values()):
        raise ValueError("An existing test account is missing or inactive")
    experts = list(Expert.objects.filter(user_id__in=expert_user_ids))
    if {row.user_id for row in experts} != set(expert_user_ids):
        raise ValueError("Existing test experts are required")
    if PartnerProgram.objects.filter(tag__startswith=prefix).exists():
        raise ValueError("Fixture already exists; preparation must not be replayed")
    if User.objects.filter(email__startswith=prefix + "-").exists():
        raise ValueError("Fixture users already exist")
    plan = dict(
        prefix=prefix,
        new_programs=4,
        new_users=18,
        solution_count=23,
        legacy_project_count=4,
        mail_sent=False,
        published=False,
        manager_id=manager_id,
        captain_ids=list(captain_ids),
        expert_user_ids=list(expert_user_ids),
        participant_id=participant_id,
        applied=False,
    )
    if not apply:
        return plan

    with transaction.atomic():
        User.objects.select_for_update().get(pk=manager_id)
        if PartnerProgram.objects.filter(tag__startswith=prefix).exists():
            raise ValueError("Fixture already exists")
        baseline = []
        for model in apps.get_models(include_auto_created=True):
            if (
                model._meta.app_label
                not in {"partner_programs", "projects", "project_rates"}
                or model._meta.proxy
            ):
                continue
            ids = list(model._base_manager.order_by("pk").values_list("pk", flat=True))
            baseline.append((model, ids, _digest(model, ids)))
        synthetic = [
            User.objects.create_user(
                email=f"{prefix}-{index:02d}@example.invalid",
                password=None,
                first_name="Приемка",
                last_name=f"PR517-{index:02d}",
                birthday="1990-01-01",
                is_active=True,
            )
            for index in range(1, 19)
        ]
        assert all(not user.has_usable_password() for user in synthetic)
        captains = [users[pk] for pk in captain_ids] + synthetic
        now = timezone.now()
        programs = []
        work = {}
        scenarios = [
            ("legacy_project", "project", "case_championship", True, True),
            ("solution", "solution", "case_championship", True, True),
            ("solution", "hackathon", "hackathon", True, False),
            ("solution", "noncompetitive", "hackathon", False, False),
        ]
        for mode, suffix, template, competitive, distributed in scenarios:
            program = PartnerProgram.objects.create(
                name=f"PR517 {key} — {suffix}",
                tag=prefix + "-" + suffix,
                description="Изолированная приемка PR517. Тестовые работы и настройки.",
                city="Москва",
                draft=True,
                projects_availability="all_users",
                data_schema={},
                solution_storage_mode=mode,
                solution_template=template,
                solution_creation_enabled=mode == "solution",
                is_competitive=competitive,
                is_distributed_evaluation=distributed,
                required_evaluators=1 if competitive else None,
                max_project_rates=1 if competitive else None,
                legacy_team_min_size=1,
                legacy_team_max_size=4,
                datetime_started=now - timezone.timedelta(days=1),
                datetime_registration_ends=now + timezone.timedelta(days=7),
                datetime_project_submission_ends=now + timezone.timedelta(days=7),
                datetime_evaluation_ends=now + timezone.timedelta(days=8),
                datetime_finished=now + timezone.timedelta(days=9),
            )
            program.managers.add(users[manager_id], users[captain_ids[0]])
            active_captains = (
                captains[:4]
                if mode == "legacy_project"
                else captains if suffix == "solution" else captains[:1]
            )
            registered = {user.pk: user for user in active_captains}
            registered.update(
                {pk: users[pk] for pk in (manager_id, participant_id, *expert_user_ids)}
            )
            for user in registered.values():
                PartnerProgramUserProfile.objects.create(
                    partner_program=program,
                    user=user,
                    partner_program_data={"qa_marker": prefix},
                )
            for expert in experts:
                expert.programs.add(program)
            fields = []
            definitions = [
                (PROGRAM_CASE_FIELD_NAME, "Кейс", "select", "case", True),
                ("pr517_description", "Описание решения", "textarea", "other", True),
            ]
            if mode == "solution":
                definitions.extend(
                    [
                        ("pr517_zero", "Число для проверки", "number", "other", False),
                        ("pr517_no", "Дополнительная опция", "checkbox", "other", False),
                    ]
                )
            if template == "hackathon":
                definitions.append(
                    ("repository", "Ссылка на репозиторий", "url", "repository", True)
                )
            for position, (name, label, kind, purpose, required_field) in enumerate(
                definitions
            ):
                fields.append(
                    PartnerProgramField.objects.create(
                        partner_program=program,
                        name=name,
                        label=label,
                        field_type=kind,
                        purpose=purpose,
                        is_required=required_field,
                        show_filter=purpose == "case",
                        position=position,
                        options="Город|Образование" if purpose == "case" else "",
                        solution_options=(
                            ["Город", "Образование"] if purpose == "case" else None
                        ),
                    )
                )
            criteria = [("int", "PR517 Баллы"), ("bool", "PR517 Да/Нет")]
            for kind, name in criteria if competitive else []:
                Criteria.objects.create(
                    partner_program=program,
                    name=name,
                    type=kind,
                    min_value=0 if kind == "int" else None,
                    max_value=10 if kind == "int" else None,
                )
            ids = []
            for index, captain in enumerate(active_captains):
                case = "Образование" if index == len(active_captains) - 1 else "Город"
                name = f"PR517 {key} {suffix} {index + 1:02d}"
                if mode == "legacy_project":
                    project = Project.objects.create(
                        leader=captain,
                        name=name,
                        description="PR517: тестовое описание работы.",
                        draft=False,
                        is_public=False,
                    )
                    link = PartnerProgramProject.objects.create(
                        partner_program=program, project=project
                    )
                    for field, value in zip(
                        fields, [case, "PR517: материалы тестовой работы."]
                    ):
                        PartnerProgramFieldValue.objects.create(
                            field=field, program_project=link, value_text=value
                        )
                    ids.append(
                        {
                            "project_id": project.pk,
                            "program_link_id": link.pk,
                            "captain_id": captain.pk,
                        }
                    )
                else:
                    solution, created = create_solution(
                        program.pk, captain, {"name": name}
                    )
                    assert created
                    revision = form_data(program)["revision"]
                    values = {
                        PROGRAM_CASE_FIELD_NAME: case,
                        "pr517_description": "PR517: материалы тестовой работы.",
                        "pr517_zero": 0,
                        "pr517_no": False,
                        "repository": "https://example.invalid/pr517",
                    }
                    update_solution(
                        program_id=program.pk,
                        solution_id=solution.pk,
                        actor=captain,
                        expected_version=solution.version,
                        expected_form_revision=revision,
                        answers=[
                            {"field_id": field.pk, "value": values[field.name]}
                            for field in fields
                        ],
                    )
                    solution.refresh_from_db()
                    if competitive and (index in (1, 3, 4) or suffix == "hackathon"):
                        submit_solution(
                            program_id=program.pk,
                            solution_id=solution.pk,
                            actor=captain,
                            expected_version=solution.version,
                            expected_form_revision=revision,
                        )
                    ids.append({"solution_id": solution.pk, "captain_id": captain.pk})
            if mode == "solution":
                call_command(
                    "set_solution_creation",
                    program_id=program.pk,
                    disable=True,
                    apply=True,
                    stdout=io.StringIO(),
                )
            programs.append(
                {
                    "id": program.pk,
                    "mode": mode,
                    "scenario": suffix,
                    "template": template,
                    "competitive": competitive,
                    "draft": True,
                    "creation_enabled": False,
                    "work": ids,
                }
            )
            work[mode if mode == "legacy_project" else suffix] = len(ids)
        for model, ids, before in baseline:
            if _digest(model, ids) != before:
                raise AssertionError("Existing data changed: " + model._meta.label)
        return {
            **plan,
            "applied": True,
            "programs": programs,
            "synthetic_user_ids": [user.pk for user in synthetic],
            "old_models_unchanged": len(baseline),
            "work_counts": work,
        }


def main():
    sys.path.insert(0, os.getcwd())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "procollab.settings")
    import django

    django.setup()
    assert re.fullmatch(r"[0-9a-f]{40}", os.environ["VERIFY_EXPECTED_API_SHA"])
    assert os.environ["VERIFY_PHASE"] == "prepare_pr517_closeout"
    apply = os.environ["VERIFY_FIXTURE_APPLY"]
    assert apply in ("true", "false")
    result = prepare(
        os.environ["VERIFY_FIXTURE_KEY"],
        int(os.environ["VERIFY_MANAGER_ID"]),
        (11, 59, 84),
        (28, 59),
        341,
        apply=apply == "true",
    )
    if result["applied"]:
        receipt = Path("/procollab/log") / (result["prefix"] + ".json")
        receipt.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        receipt.chmod(0o600)
    sys.stdout.write("PR517_CLOSEOUT=" + json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

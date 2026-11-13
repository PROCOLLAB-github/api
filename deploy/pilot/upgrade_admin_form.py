"""Исправить только форму менеджеров действующего white label пилота."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
import upgrade_expert as previous  # noqa: E402

hosted, files, auth, overall = (
    previous.hosted,
    previous.files,
    previous.auth,
    previous.overall,
)
ROOT = hosted.NEW
BASE = json.loads((Path(__file__).parent / "admin_form_base.json").read_text())
RECORD = ROOT / "admin-form-upgrade.json"
IDENTITY = "hosted-v2-admin-empty-schema"
STEP_LABEL = "io.procollab.pilot.admin-form.step"
PATCH_FILES = ("partner_programs/admin.py",)
HELPERS = previous.HELPERS | {"upgrade_admin_form.py", "admin_form_base.json"}
require = hosted.require


def verify_bundle(bundle):
    require(
        bundle.resolve() == bundle and not bundle.is_symlink(),
        "Нужен обычный каталог пакета.",
    )
    manifest = json.loads((bundle / "admin-form-manifest.json").read_text())
    require(manifest.get("format") == IDENTITY, "Чужой формат пакета.")
    for key in ("backend_revision", "base_backend_revision", "frontend_revision"):
        require(
            manifest.get(key) == BASE[key] and re.fullmatch(r"[a-f0-9]{40}", BASE[key]),
            "Другая версия пакета.",
        )
    require(
        re.fullmatch(r"[a-f0-9]{40}", manifest.get("tooling_revision", "")),
        "Нет revision установщика.",
    )
    require(
        json.loads((bundle / "admin_form_base.json").read_text()) == BASE,
        "Другой baseline.",
    )
    expected = auth.hashes(manifest["files"])
    require(
        set(expected) == HELPERS | {"api/" + name for name in PATCH_FILES},
        "Посторонние файлы пакета.",
    )
    actual = set()
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Ссылка внутри пакета.")
        if path.is_file():
            actual.add(str(path.relative_to(bundle)))
    require(
        actual == set(expected) | {"admin-form-manifest.json"}, "Изменен состав пакета."
    )
    for name, digest in expected.items():
        require(hosted.digest(bundle / name) == digest, "Поврежден файл: " + name)
    require(
        expected["api/partner_programs/admin.py"] == BASE["target_hash"],
        "Другой API формы.",
    )
    return manifest


def runtime(container, updated):
    expected = {**previous.BASE["runtime_hashes"], **previous.BASE["target_hashes"]}
    require(
        expected["partner_programs/admin.py"] == BASE["base_hash"],
        "Другой исходный admin.",
    )
    if updated:
        expected["partner_programs/admin.py"] = BASE["target_hash"]
    script = (
        "import hashlib,json,sys;from pathlib import Path;root=Path('/procollab');"
        "names=json.load(sys.stdin);print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() "
        "if (root/n).is_file() and not (root/n).is_symlink() else None for n in names}))"
    )
    response = hosted.docker(
        "exec",
        "-i",
        container["Id"],
        "python",
        "-B",
        "-c",
        script,
        input=json.dumps(sorted(expected)),
        capture_output=True,
        text=True,
        timeout=45,
    )
    require(
        response.returncode == 0 and json.loads(response.stdout) == expected,
        "Неизвестный код API пилота.",
    )


def outside_snapshot(container):
    snapshot = previous.outside_snapshot(container)
    snapshot["files"][str(previous.RECORD)] = hosted.digest(previous.RECORD)
    return snapshot


def verify_outside(record):
    require(
        outside_snapshot(hosted.inspect(record["old_container_id"])) == record["outside"],
        "Изменились DEV, БД, nginx, прежний пилот или защищенные файлы.",
    )
    return hosted.dev_health()


def save(record):
    value = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", value)
    hosted.private_write(RECORD, value)


def load_record():
    require(RECORD.is_file() and not RECORD.is_symlink(), "Нет записи обновления формы.")
    record = json.loads(RECORD.read_text())
    require(
        record.get("identity") == IDENTITY
        and record.get("release") == BASE["backend_revision"]
        and record.get("phase") in ("prepared", "active", "rolled_back")
        and re.fullmatch(r"[a-f0-9]{12}", record.get("step", "")),
        "Чужая запись обновления.",
    )
    require(
        Path(record["backup"]) == ROOT / "backup" / ("admin-form-" + record["step"])
        and hosted.owned_path(Path(record["backup"])) == Path(record["backup"]),
        "Чужой backup.",
    )
    require(
        record["old_name"] == hosted.WEB + "-before-" + record["step"]
        and re.fullmatch(r"[a-f0-9]{64}", record["old_container_id"]),
        "Чужой прежний web.",
    )
    return record


def verify_frontend():
    for name, digest in previous.BASE["target_frontend_files"].items():
        require(
            hosted.digest(auth.frontend_path(name)) == digest,
            "Изменился интерфейс пилота.",
        )
    auth.verify_live(previous.BASE["target_frontend_files"]["index.html"])


def check(bundle):
    hosted.scope()
    verify_bundle(bundle)
    require(
        BASE["base_backend_revision"] == previous.BASE["backend_revision"]
        and BASE["frontend_revision"] == previous.BASE["frontend_revision"],
        "Нужен принятый кабинет эксперта.",
    )
    if RECORD.exists():
        record = load_record()
        require(record["phase"] == "rolled_back", "Используйте status или rollback.")
        status()
    else:
        require(
            previous.status()["phase"] == "active", "Сначала установите кабинет эксперта."
        )
    current = hosted.candidate()
    runtime(current, False)
    verify_frontend()
    available = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    require(
        int(available["MemAvailable"].split()[0]) >= 1536 * 1024,
        "Недостаточно RAM с запасом для DEV.",
    )
    require(
        shutil.disk_usage(ROOT).free >= 2 * 2**30 + 128 * 2**20,
        "Недостаточно диска с запасом для DEV.",
    )
    return hosted.state_read(), current


def overlay_args(current, sources):
    target = "/procollab/partner_programs/admin.py"
    result = []
    for mount in current["Mounts"]:
        if mount["Destination"] in {target, "/procollab/pilot-data", "/procollab/log"}:
            continue
        require(mount["Type"] == "bind" and not mount["RW"], "Неизвестный mount.")
        result.extend(
            (
                "--mount",
                f"type=bind,src={mount['Source']},dst={mount['Destination']},readonly",
            )
        )
    result.extend(
        ("--mount", f"type=bind,src={sources/PATCH_FILES[0]},dst={target},readonly")
    )
    return result


def verify_replacement(before, after, sources):
    normalized = json.loads(json.dumps(after))
    normalized["Config"]["Labels"].pop(STEP_LABEL, None)
    overall.preserved_configuration(before, normalized)

    def mounts(container):
        result = {
            m["Destination"]: (m["Type"], m["Source"], m["RW"])
            for m in container["Mounts"]
        }
        require(len(result) == len(container["Mounts"]), "Повторяющийся mount.")
        return result

    expected = mounts(before)
    expected["/procollab/" + PATCH_FILES[0]] = (
        "bind",
        str(sources / PATCH_FILES[0]),
        False,
    )
    require(mounts(after) == expected, "Изменились данные, логи или прежние overlays.")


def scores_snapshot(container):
    script = (
        "import django,hashlib,json;django.setup();from project_rates.models import ProjectScore;"
        "rows=list(ProjectScore.objects.order_by('pk').values_list('pk','project_id','user_id','criteria_id','value'));"
        "print(hashlib.sha256(json.dumps(rows,default=str).encode()).hexdigest())"
    )
    result = hosted.docker(
        "exec",
        container["Id"],
        "python",
        "-B",
        "-c",
        script,
        capture_output=True,
        text=True,
        timeout=45,
    )
    require(
        result.returncode == 0 and re.fullmatch(r"[a-f0-9]{64}", result.stdout.strip()),
        "Не проверены прежние оценки.",
    )
    return result.stdout.strip()


def form_smoke(container):
    script = (
        "import django;django.setup();from django.db import connection;"
        "from django.db.migrations.executor import MigrationExecutor;"
        "from partner_programs.admin import PartnerProgramAdmin;"
        "from partner_programs.models import PartnerProgram;"
        f"assert connection.settings_dict['NAME']=={hosted.DB_NAME!r};"
        "e=MigrationExecutor(connection);assert not e.migration_plan(e.loader.graph.leaf_nodes());"
        "f=PartnerProgramAdmin.PartnerProgramAdminForm(instance=PartnerProgram(data_schema={}));"
        "assert f.fields['data_schema'].required is False;"
        "f.cleaned_data={'data_schema':{}};assert f.clean_data_schema()=={};"
        "f.cleaned_data={'data_schema':None};assert f.clean_data_schema()=={};print('ok')"
    )
    result = hosted.docker(
        "exec",
        container["Id"],
        "python",
        "-B",
        "-c",
        script,
        capture_output=True,
        text=True,
        timeout=45,
    )
    require(
        result.returncode == 0 and result.stdout.strip() == "ok",
        "Не проверена форма admin или появились миграции.",
    )


def rollback(record):
    if record["phase"] == "rolled_back":
        return status()
    verify_outside(record)
    candidate = hosted.candidate()
    if candidate and candidate["Id"] != record["old_container_id"]:
        require(
            (candidate["Config"].get("Labels") or {}).get(STEP_LABEL) == record["step"],
            "Текущий web изменен снаружи.",
        )

    def writer(value):
        value["restored_web"] = overall.container_identity(hosted.inspect(hosted.WEB))
        save(value)

    result = files.rollback(record, record_writer=writer)
    verify_outside(record)
    runtime(hosted.candidate(), False)
    verify_frontend()
    return result


def status():
    hosted.scope()
    record = load_record()
    verify_outside(record)
    if record["phase"] == "prepared":
        return {"phase": "prepared", "required_next": "rollback"}
    active = record["phase"] == "active"
    web = hosted.candidate()
    require(
        web
        and web["State"]["Running"]
        and overall.container_identity(web)
        == record["new_web" if active else "restored_web"],
        "Изменился web пилота.",
    )
    require(
        hosted.state_read() == record["new_state" if active else "previous_state"],
        "Изменилось состояние пилота.",
    )
    runtime(web, active)
    verify_frontend()
    if active:
        form_smoke(web)
    return {
        "phase": record["phase"],
        "backend_revision": BASE["backend_revision"],
        "frontend_revision": BASE["frontend_revision"],
        "database_preserved": hosted.DB_NAME,
        "migration_count": 0,
        "image_reused": True,
        "nginx_changed": False,
        "frontend_changed": False,
        "dev_http": 200,
        "backup": record["backup"],
    }


def apply(bundle):
    if RECORD.exists() and load_record()["phase"] == "active":
        verify_bundle(bundle)
        return status()
    state, current = check(bundle)
    step = uuid.uuid4().hex[:12]
    backup = hosted.owned_path(ROOT / "backup" / ("admin-form-" + step))
    backup.mkdir(mode=0o700)
    sources = hosted.owned_path(
        ROOT / "releases" / ("admin-form-" + BASE["backend_revision"]) / "backend"
    )
    target = hosted.owned_path(sources / PATCH_FILES[0])
    if target.exists():
        require(
            hosted.digest(target) == BASE["target_hash"], "Изменился целевой release."
        )
    else:
        files.copy_atomic(bundle / "api" / PATCH_FILES[0], target)
    record = {
        "identity": IDENTITY,
        "release": BASE["backend_revision"],
        "step": step,
        "phase": "prepared",
        "backup": str(backup),
        "old_container_id": current["Id"],
        "old_name": hosted.WEB + "-before-" + step,
        "old_web": overall.container_identity(current),
        "previous_state": state,
        "outside": outside_snapshot(current),
        "frontend": {},
        "case_before": overall.case_snapshot(current),
        "scores_before": scores_snapshot(current),
    }
    files.copy_atomic(ROOT / ".env", backup / "environment.env", mode=0o600)
    overall.progress(
        "Сохраняю проверенную резервную копию БД. Меняется только admin.py пилота."
    )
    files.backup_database(backup)
    save(record)
    try:
        verify_outside(record)
        hosted.docker(
            "rename", hosted.WEB, record["old_name"], capture_output=True, check=True
        )
        hosted.docker(
            "stop",
            "--time",
            "20",
            record["old_name"],
            capture_output=True,
            check=True,
            timeout=45,
        )
        labels = []
        for name, value in (current["Config"].get("Labels") or {}).items():
            if name not in (files.REVISION_LABEL, STEP_LABEL, hosted.LABEL):
                labels.extend(("--label", name + "=" + value))
        result = hosted.docker(
            "run",
            "-d",
            "--name",
            hosted.WEB,
            "--restart",
            "unless-stopped",
            "-p",
            "127.0.0.1:18319:8000",
            "--label",
            files.REVISION_LABEL + "=" + record["release"],
            "--label",
            STEP_LABEL + "=" + step,
            *labels,
            *overlay_args(current, sources),
            *overall.app_args(current, backup / "environment.env"),
            *current["Config"]["Cmd"],
            capture_output=True,
            text=True,
            check=True,
        )
        record["candidate_id"] = result.stdout.strip()
        save(record)
        web = hosted.candidate()
        verify_replacement(current, web, sources)
        record["new_web"] = overall.container_identity(web)
        save(record)
        overall.wait_for_web()
        runtime(web, True)
        form_smoke(web)
        previous.previous.smoke()
        previous.cabinet_smoke()
        require(
            overall.case_snapshot(web) == record["case_before"]
            and scores_snapshot(web) == record["scores_before"],
            "Изменились прежние оценки или отчеты.",
        )
        verify_frontend()
        verify_outside(record)
        new_state = {
            **state,
            "app_patch_revision": record["release"],
            "admin_form_revision": record["release"],
            "app_patch_files": {
                **state.get("app_patch_files", {}),
                PATCH_FILES[0]: BASE["target_hash"],
            },
        }
        hosted.state_write(new_state)
        record.update(phase="active", new_state=new_state)
        save(record)
        return status()
    except BaseException as error:
        hosted.private_write(
            backup / "failure.txt", type(error).__name__ + ": " + str(error)
        )
        try:
            rollback(record)
        except BaseException as rollback_error:
            raise hosted.Refused(
                "Откат не завершен. Backup: " + str(backup) + ". " + str(rollback_error)
            ) from error
        raise hosted.Refused(
            "Обновление остановлено; прежний web восстановлен. Backup: " + str(backup)
        ) from error


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply", "status", "rollback"))
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        hosted.scope()
        with hosted.locked():
            if args.command == "status":
                result = status()
            elif args.command == "rollback":
                result = rollback(load_record())
            else:
                require(args.bundle is not None, "Укажите --bundle.")
                bundle = args.bundle.resolve()
                if args.command == "apply":
                    result = apply(bundle)
                else:
                    check(bundle)
                    result = {
                        "changes_applied": False,
                        "backend_revision": BASE["backend_revision"],
                        "migration_count": 0,
                        "frontend_changed": False,
                        "nginx_changed": False,
                        "dev_http": 200,
                    }
    except (hosted.Refused, OSError, ValueError) as error:
        sys.exit("ОСТАНОВЛЕНО: " + str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

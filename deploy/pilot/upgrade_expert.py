"""Точечное обновление единого кабинета только на известном white label пилоте."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
import upgrade_management as previous  # noqa: E402

hosted, files, auth, overall = (
    previous.hosted,
    previous.files,
    previous.auth,
    previous.overall,
)
ROOT = hosted.NEW
BASE = json.loads((Path(__file__).parent / "expert_base.json").read_text())
RECORD = ROOT / "expert-upgrade.json"
QA_RECORD = ROOT / "expert-qa.json"
IDENTITY = "hosted-v2-expert-workspace"
STEP_LABEL = "io.procollab.pilot.expert.step"
PATCH_FILES = tuple(BASE["target_hashes"])
HELPERS = previous.HELPERS | {
    "upgrade_expert.py",
    "expert_base.json",
    "prepare_expert_qa.py",
}
MIGRATIONS = {
    ("partner_programs", "0044_organizer_expert_identities"),
    ("partner_programs", "0046_merge_organizer_experts_and_quiz"),
}
require = hosted.require


def verify_bundle(bundle):
    require(
        bundle.resolve() == bundle and not bundle.is_symlink(),
        "Нужен обычный каталог пакета.",
    )
    manifest = json.loads((bundle / "expert-manifest.json").read_text())
    require(manifest.get("format") == IDENTITY, "Чужой формат пакета.")
    require(
        re.fullmatch(r"[a-f0-9]{40}", manifest.get("tooling_revision", "")),
        "Нет revision установщика.",
    )
    for key in (
        "backend_revision",
        "frontend_revision",
        "base_backend_revision",
        "base_frontend_revision",
    ):
        require(
            manifest.get(key) == BASE[key] and re.fullmatch(r"[a-f0-9]{40}", BASE[key]),
            "Чужая версия пакета.",
        )
    require(
        json.loads((bundle / "expert_base.json").read_text()) == BASE,
        "Другой baseline пакета.",
    )
    expected = auth.hashes(manifest["files"])
    frontend = auth.hashes(manifest["new_files"])
    require(frontend == BASE["target_frontend_files"], "Неизвестная сборка интерфейса.")
    changed = {
        "frontend/" + name
        for name, digest in frontend.items()
        if BASE["frontend_files"].get(name) != digest
    }
    require(
        set(expected) == HELPERS | {"api/" + name for name in PATCH_FILES} | changed,
        "Посторонние файлы в пакете.",
    )
    actual = set()
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Ссылка внутри пакета.")
        if path.is_file():
            actual.add(str(path.relative_to(bundle)))
    require(actual == set(expected) | {"expert-manifest.json"}, "Изменен состав пакета.")
    for name, digest in expected.items():
        require(hosted.digest(bundle / name) == digest, "Поврежден файл пакета: " + name)
    for name, digest in BASE["target_hashes"].items():
        require(expected["api/" + name] == digest, "Другой API: " + name)
    for name, digest in frontend.items():
        if "frontend/" + name in expected:
            require(expected["frontend/" + name] == digest, "Другой файл интерфейса.")
    index = (bundle / "frontend/index.html").read_text()
    require(
        'content="white-label-pilot-v1"' in index and 'data-theme="light"' in index,
        "Нужна сборка white label пилота.",
    )
    return manifest


def runtime(container, updated):
    expected = dict(BASE["runtime_hashes"])
    for name in PATCH_FILES:
        expected.setdefault(name, None)
    if updated:
        expected.update(BASE["target_hashes"])
    script = (
        "import hashlib,json,sys;from pathlib import Path;root=Path('/procollab');"
        "names=json.load(sys.stdin);print(json.dumps({n:hashlib.sha256((root/n).read_bytes())"
        ".hexdigest() if (root/n).is_file() and not (root/n).is_symlink() else None for n in names}))"
    )
    result = hosted.docker(
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
        result.returncode == 0 and json.loads(result.stdout) == expected,
        "Неизвестный код API пилота.",
    )


def outside_snapshot(container):
    snapshot = previous.outside_snapshot(container)
    snapshot["files"][str(hosted.ROUTES)] = hosted.digest(hosted.ROUTES)
    snapshot["files"][str(previous.RECORD)] = hosted.digest(previous.RECORD)
    return snapshot


def verify_outside(record):
    require(
        outside_snapshot(hosted.inspect(record["old_container_id"])) == record["outside"],
        "Изменились DEV, БД, nginx, прежний пилот или защищенные файлы.",
    )
    return hosted.dev_health()


def verify_predecessor(record):
    before = record["outside"]
    after = previous.outside_snapshot(hosted.inspect(record["old_container_id"]))
    require(
        set(before["containers"]) == set(after["containers"]),
        "Изменился состав защищенных контейнеров.",
    )

    def fixed(snapshot):
        return {
            **snapshot,
            "containers": {
                name: value
                for name, value in snapshot["containers"].items()
                if name not in previous.DEV_CONTAINERS
            },
        }

    require(
        fixed(before) == fixed(after),
        "Пилот, БД, nginx или защищенные файлы изменились после принятой версии.",
    )
    return hosted.dev_health()


def save(record):
    value = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", value)
    hosted.private_write(RECORD, value)


def load_record():
    require(
        RECORD.is_file() and not RECORD.is_symlink(), "Нет записи обновления кабинета."
    )
    record = json.loads(RECORD.read_text())
    require(
        record.get("identity") == IDENTITY
        and record.get("release") == BASE["backend_revision"]
        and record.get("frontend_revision") == BASE["frontend_revision"]
        and record.get("phase") in ("prepared", "active", "rolled_back")
        and re.fullmatch(r"[a-f0-9]{12}", record.get("step", "")),
        "Чужая запись обновления.",
    )
    require(
        Path(record["backup"]) == ROOT / "backup" / ("expert-" + record["step"])
        and hosted.owned_path(Path(record["backup"])) == Path(record["backup"]),
        "Чужой backup.",
    )
    require(
        record["old_name"] == hosted.WEB + "-before-" + record["step"]
        and re.fullmatch(r"[a-f0-9]{64}", record["old_container_id"]),
        "Чужой прежний web.",
    )
    auth.hashes(record["new_files"])
    return record


def check(bundle):
    hosted.scope()
    manifest = verify_bundle(bundle)
    restored = load_record() if RECORD.exists() else None
    if restored:
        require(
            restored["phase"] == "rolled_back",
            "Обновление уже подготовлено: используйте status или rollback.",
        )
        verify_outside(restored)
    parent = previous.load_record()
    require(
        parent["phase"] == "active"
        and parent["release"] == BASE["base_backend_revision"]
        and parent["frontend_revision"] == BASE["base_frontend_revision"],
        "Нужна принятая версия управления пилотом.",
    )
    verify_predecessor(parent)
    web = hosted.candidate()
    require(
        web
        and overall.container_identity(web)
        == (restored["restored_web"] if restored else parent["new_web"]),
        "Изменился web пилота.",
    )
    state = hosted.state_read()
    require(state == parent["new_state"], "Изменилось состояние пилота.")
    runtime(web, False)
    for name, digest in BASE["frontend_files"].items():
        require(
            hosted.digest(auth.frontend_path(name)) == digest,
            "Изменился интерфейс: " + name,
        )
    for name, digest in manifest["new_files"].items():
        target = auth.frontend_path(name)
        if name not in BASE["frontend_files"] and target.exists():
            require(
                target.is_file() and hosted.digest(target) == digest,
                "Новый путь уже занят.",
            )
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    require(
        int(memory["MemAvailable"].split()[0]) >= 1536 * 1024,
        "Недостаточно RAM с запасом для DEV.",
    )
    size = sum((bundle / name).stat().st_size for name in manifest["files"])
    require(
        shutil.disk_usage(ROOT).free >= 2 * 2**30 + 2 * size + 128 * 2**20,
        "Недостаточно диска с запасом для DEV.",
    )
    auth.api_smoke()
    auth.verify_live(BASE["frontend_files"]["index.html"])
    return state, web, manifest


def overlay_args(current, sources):
    replaced = {"/procollab/" + name for name in PATCH_FILES}
    result = []
    for mount in current["Mounts"]:
        if mount["Destination"] in replaced | {"/procollab/pilot-data", "/procollab/log"}:
            continue
        require(mount["Type"] == "bind" and not mount["RW"], "Неизвестный mount.")
        result.extend(
            (
                "--mount",
                f"type=bind,src={mount['Source']},dst={mount['Destination']},readonly",
            )
        )
    for name in PATCH_FILES:
        result.extend(
            ("--mount", f"type=bind,src={sources/name},dst=/procollab/{name},readonly")
        )
    return result


def verify_replacement(before, after, sources):
    normalized = json.loads(json.dumps(after))
    normalized["Config"]["Labels"].pop(STEP_LABEL, None)
    overall.preserved_configuration(before, normalized)

    def mounts(container):
        items = {
            m["Destination"]: (m["Type"], m["Source"], m["RW"])
            for m in container["Mounts"]
        }
        require(len(items) == len(container["Mounts"]), "Повторяющийся mount.")
        return items

    expected = mounts(before)
    expected.update(
        {
            "/procollab/" + name: ("bind", str(sources / name), False)
            for name in PATCH_FILES
        }
    )
    require(
        mounts(after) == expected, "Изменились данные, логи или посторонние overlays."
    )


def migrate(container):
    script = "\n".join(
        [
            "import django,json;django.setup()",
            "from django.db import connection",
            "from django.db.migrations.executor import MigrationExecutor",
            "db=connection.settings_dict",
            f"assert db['NAME']=={hosted.DB_NAME!r} and db['USER']=={hosted.DB_ROLE!r} and db['HOST']=='db'",
            "with connection.cursor() as cursor:",
            "    cursor.execute(\"SET lock_timeout = '10s'\")",
            "    cursor.execute(\"SET statement_timeout = '120s'\")",
            "executor=MigrationExecutor(connection)",
            "targets=executor.loader.graph.leaf_nodes()",
            "plan=executor.migration_plan(targets)",
            f"assert all(not backwards and (m.app_label,m.name) in {MIGRATIONS!r} for m,backwards in plan)",
            "for migration,_ in plan:",
            "    if migration.name=='0044_organizer_expert_identities':",
            "        assert len(migration.operations)==1 and type(migration.operations[0]).__name__=='RunPython'",
            "        assert migration.operations[0].code.__name__=='create_organizer_expert_identities'",
            "    else:",
            "        assert not migration.operations",
            "executor.migrate(targets)",
            "assert not MigrationExecutor(connection).migration_plan(targets)",
            "print(json.dumps({'django':django.get_version(),"
            "'migrations_applied':[[m.app_label,m.name] for m,_ in plan]}))",
        ]
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
        timeout=180,
    )
    require(
        result.returncode == 0, "Не подтверждено применение двух добавочных миграций."
    )
    return json.loads(result.stdout.splitlines()[-1])


def cabinet_smoke():
    headers = {
        "Host": "pilot.procollab.ru",
        "X-Forwarded-Proto": "https",
        "Content-Type": "application/json",
    }
    origin = "http://127.0.0.1:18319/backend"
    code, _, body = hosted.health(
        origin + "/api/token/",
        headers=headers,
        body=json.dumps(
            {
                "email": "organizer@example.test",
                "password": hosted.environment()["PILOT_ACCOUNT_PASSWORD"],
            }
        ).encode(),
    )
    require(code == 200, "Не прошел вход организатора.")
    tokens = json.loads(body)
    headers["Authorization"] = "Bearer " + tokens["access"]
    try:
        code, _, body = hosted.health(
            origin + "/evaluation/applications/?program_id=1", headers=headers
        )
        require(
            code == 200 and isinstance(json.loads(body).get("results"), list),
            "Единый кабинет недоступен в режиме проектов.",
        )
    finally:
        code, _, _ = hosted.health(
            origin + "/auth/logout/",
            headers=headers,
            body=json.dumps({"refresh_token": tokens["refresh"]}).encode(),
        )
        require(code == 205, "Не закрыта проверочная сессия.")


def rollback(record):
    if record["phase"] == "rolled_back":
        return status()
    verify_outside(record)
    current = hosted.candidate()
    if current and current["Id"] != record["old_container_id"]:
        require(
            (current["Config"].get("Labels") or {}).get(STEP_LABEL) == record["step"],
            "Текущий web изменен снаружи.",
        )

    def writer(value):
        value["restored_web"] = overall.container_identity(hosted.inspect(hosted.WEB))
        save(value)

    result = files.rollback(record, record_writer=writer)
    verify_outside(record)
    auth.verify_live(BASE["frontend_files"]["index.html"])
    return {
        **result,
        "additive_expert_identities_retained": True,
        "database_restored": False,
    }


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
    expected = BASE["target_frontend_files"] if active else BASE["frontend_files"]
    for name, digest in expected.items():
        require(
            hosted.digest(auth.frontend_path(name)) == digest,
            "Изменился интерфейс: " + name,
        )
    auth.verify_live(expected["index.html"])
    if active:
        cabinet_smoke()
    return {
        "phase": record["phase"],
        "expert_revision": record["release"],
        "frontend_revision": record["frontend_revision"],
        "database_preserved": hosted.DB_NAME,
        "dev_http": 200,
        "nginx_changed": False,
        "image_reused": True,
        "backup": record["backup"],
    }


def apply(bundle):
    if RECORD.exists():
        verify_bundle(bundle)
        phase = load_record()["phase"]
        if phase == "active":
            return status()
        require(phase == "rolled_back", "Незавершенная установка: используйте rollback.")
    state, current, manifest = check(bundle)
    overall.progress(
        "Проверки пройдены. Сохраняю БД, прежний интерфейс и настройки пилота."
    )
    step = uuid.uuid4().hex[:12]
    backup = hosted.owned_path(ROOT / "backup" / ("expert-" + step))
    backup.mkdir(mode=0o700)
    sources = hosted.owned_path(
        ROOT / "releases" / ("expert-" + BASE["backend_revision"]) / "backend"
    )
    for name, digest in BASE["target_hashes"].items():
        target = hosted.owned_path(sources / name)
        if target.exists():
            require(hosted.digest(target) == digest, "Изменился целевой release.")
        else:
            files.copy_atomic(bundle / "api" / name, target)
    record = {
        "identity": IDENTITY,
        "release": BASE["backend_revision"],
        "frontend_revision": BASE["frontend_revision"],
        "step": step,
        "phase": "prepared",
        "backup": str(backup),
        "old_container_id": current["Id"],
        "old_name": hosted.WEB + "-before-" + step,
        "old_web": overall.container_identity(current),
        "previous_state": state,
        "outside": outside_snapshot(current),
        "installer_sha256": hosted.digest(Path(__file__).resolve()),
        "frontend": {},
        "new_files": manifest["new_files"],
        "case_before": overall.case_snapshot(current),
    }
    files.copy_atomic(ROOT / ".env", backup / "environment.env", mode=0o600)
    for name, digest in manifest["new_files"].items():
        target = auth.frontend_path(name)
        old = hosted.digest(target) if target.exists() else None
        if old != digest:
            record["frontend"][name] = {"before": old, "after": digest}
            if old:
                files.copy_atomic(target, backup / "frontend" / name, mode=0o600)
    files.backup_database(backup)
    save(record)
    try:
        verify_outside(record)
        overall.progress(
            "Резервная копия проверена. Заменяю только web пилота; image и БД прежние."
        )
        hosted.docker(
            "rename", hosted.WEB, record["old_name"], capture_output=True, check=True
        )
        hosted.docker(
            "stop",
            "--time",
            "20",
            record["old_name"],
            capture_output=True,
            timeout=45,
            check=True,
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
        candidate = hosted.candidate()
        verify_replacement(current, candidate, sources)
        record["new_web"] = overall.container_identity(candidate)
        save(record)
        overall.wait_for_web()
        runtime(candidate, True)
        record["migrations"] = migrate(candidate)
        previous.smoke()
        cabinet_smoke()
        require(
            overall.case_snapshot(candidate) == record["case_before"],
            "Изменились прежние оценки, команды или участники.",
        )
        verify_outside(record)
        overall.progress(
            "API, кабинет, роли и прежние отчеты проверены. Публикую только интерфейс пилота."
        )
        for name in record["frontend"]:
            if name != "index.html":
                files.copy_atomic(bundle / "frontend" / name, auth.frontend_path(name))
        files.copy_atomic(
            bundle / "frontend/index.html", auth.frontend_path("index.html")
        )
        previous.smoke(public=True, index=manifest["new_files"]["index.html"])
        verify_outside(record)
        new_state = {
            **state,
            "app_patch_revision": record["release"],
            "app_patch_files": {
                **state.get("app_patch_files", {}),
                **BASE["target_hashes"],
            },
            "expert_revision": record["release"],
            "expert_frontend_revision": record["frontend_revision"],
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
            "Обновление остановлено; прежний web и интерфейс восстановлены. Backup: "
            + str(backup)
        ) from error


def prepare_qa(bundle):
    verify_bundle(bundle)
    require(status()["phase"] == "active", "Сначала установите кабинет.")
    if QA_RECORD.exists():
        require(QA_RECORD.is_file() and not QA_RECORD.is_symlink(), "Чужой файл приемки.")
        data = json.loads(QA_RECORD.read_text())
        require(
            data.get("release") == BASE["backend_revision"],
            "Другой набор приемки уже существует.",
        )
        return data
    key = "expert-" + uuid.uuid4().hex[:12]
    script = (bundle / "prepare_expert_qa.py").read_text()
    container = hosted.candidate()
    result = hosted.docker(
        "exec",
        "-i",
        container["Id"],
        "python",
        "-B",
        "-c",
        script,
        input=json.dumps(
            {"key": key, "password": hosted.environment()["PILOT_ACCOUNT_PASSWORD"]}
        ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    require(
        result.returncode == 0,
        "Не подготовлен отдельный набор приемки; существующие данные не менялись.",
    )
    data = {
        "release": BASE["backend_revision"],
        **json.loads(result.stdout.splitlines()[-1]),
    }
    hosted.private_write(QA_RECORD, json.dumps(data, ensure_ascii=False, indent=2))
    return data


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("check", "apply", "status", "rollback", "prepare-qa")
    )
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
                elif args.command == "prepare-qa":
                    result = prepare_qa(bundle)
                else:
                    check(bundle)
                    result = {
                        "changes_applied": False,
                        "backend_revision": BASE["backend_revision"],
                        "frontend_revision": BASE["frontend_revision"],
                        "migration_count": 2,
                        "dev_http": 200,
                        "image_reused": True,
                        "nginx_changed": False,
                        "dev_guard": "current_healthy_snapshot",
                    }
    except (hosted.Refused, OSError, ValueError) as error:
        sys.exit("ОСТАНОВЛЕНО: " + str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

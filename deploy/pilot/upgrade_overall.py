"""Общий рейтинг только для известного пилота после весов и исправления входа."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True
import hosted  # noqa: E402
import upgrade_frontend as auth  # noqa: E402
import upgrade_invites as files  # noqa: E402

ROOT = hosted.NEW
RECORD = ROOT / "overall-upgrade.json"
BASE = json.loads((Path(__file__).parent / "overall_base.json").read_text())
IDENTITY = "hosted-v2-overall-upgrade"
STEP_LABEL = "io.procollab.pilot.overall.step"
PATCH_FILES = tuple(BASE["target_hashes"])
HELPERS = {
    "upgrade_overall.py",
    "overall_base.json",
    "hosted.py",
    "runtime_import.py",
    "upgrade_invites.py",
    "upgrade_frontend.py",
}
MIGRATION = ("partner_programs", "0045_program_quiz_outcome")
OUTSIDE = ("api-web-1", "api-redis-1", "api_celery", hosted.OLD_WEB, hosted.DB, hosted.PG)
require = hosted.require


def progress(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def container_identity(container):
    return [
        container["Id"],
        container["Image"],
        container["State"]["StartedAt"],
        auth.configuration_fingerprint(container),
    ]


def outside_snapshot(current):
    containers = {}
    for name in OUTSIDE:
        container = hosted.inspect(name)
        require(
            container["State"]["Running"], "Не работает защищенный контейнер: " + name
        )
        containers[name] = container_identity(container)
    paths = [
        ROOT / name
        for name in (
            ".env",
            "access.txt",
            "invite-upgrade.json",
            "weights-upgrade.json",
            "frontend-upgrade.json",
        )
    ]
    paths.extend((hosted.ROUTES, hosted.MAPS))
    paths.extend(
        hosted.owned_path(mount["Source"])
        for mount in current["Mounts"]
        if mount["Type"] == "bind" and not mount["RW"]
    )
    protected = {}
    for path in paths:
        require(path.is_file() and not path.is_symlink(), "Неизвестный защищенный файл.")
        protected[str(path)] = hosted.digest(path)
    nginx = hosted.subprocess.run(["nginx", "-T"], capture_output=True, check=True)
    return {
        "containers": containers,
        "files": protected,
        "nginx": hashlib.sha256(nginx.stdout).hexdigest(),
    }


def verify_outside(record):
    old = hosted.inspect(record["old_container_id"])
    require(
        outside_snapshot(old) == record["outside"],
        "Конфигурация dev/БД/старого пилота или защищенные файлы изменились.",
    )
    return hosted.dev_health()


def runtime_fingerprint(container):
    script = (
        "import hashlib,json,sys;from pathlib import Path;root=Path('/procollab');"
        "names=json.load(sys.stdin);print(json.dumps({n:"
        "hashlib.sha256((root/n).read_bytes()).hexdigest() "
        "if (root/n).is_file() and not (root/n).is_symlink() else None for n in names}))"
    )
    result = hosted.docker(
        "exec",
        "-i",
        container["Id"],
        "python",
        "-B",
        "-c",
        script,
        input=json.dumps(list(BASE["runtime_hashes"])),
        capture_output=True,
        text=True,
        timeout=45,
    )
    require(result.returncode == 0, "Не прочитан код работающего пилота.")
    return json.loads(result.stdout)


def verify_runtime(container, *, updated):
    expected = {**BASE["runtime_hashes"], **(BASE["target_hashes"] if updated else {})}
    actual = runtime_fingerprint(container)
    for name, value in expected.items():
        require(actual.get(name) == value, "Неизвестный код пилота: " + name)


def verify_mounts(current):
    mounts = {mount["Destination"]: mount for mount in current["Mounts"]}
    expected = {"/procollab/pilot-data": ROOT / "data", "/procollab/log": ROOT / "logs"}
    require(
        len(mounts) == len(current["Mounts"])
        and set(mounts)
        == set(expected) | {"/procollab/" + name for name in BASE["overlays"]},
        "Неизвестные mounts пилота.",
    )
    for destination, source in expected.items():
        require(
            mounts[destination]["Type"] == "bind"
            and mounts[destination]["Source"] == str(source)
            and mounts[destination]["RW"],
            "Изменен каталог данных пилота.",
        )
    for name in BASE["overlays"]:
        mount = mounts["/procollab/" + name]
        source = hosted.owned_path(mount["Source"])
        require(
            mount["Type"] == "bind"
            and not mount["RW"]
            and source.is_file()
            and hosted.digest(source) == BASE["runtime_hashes"][name],
            "Изменено прежнее исправление: " + name,
        )


def verify_bundle(bundle):
    require(
        bundle.resolve() == bundle and not bundle.is_symlink(), "Ссылка вместо пакета."
    )
    manifest = json.loads((bundle / "overall-manifest.json").read_text())
    require(
        manifest.get("format") == IDENTITY
        and manifest.get("backend_revision") == BASE["backend_revision"]
        and manifest.get("frontend_revision") == BASE["frontend_revision"]
        and manifest.get("base_backend_revision") == BASE["base_backend_revision"]
        and manifest.get("base_frontend_revision") == BASE["base_frontend_revision"],
        "Пакет для другой версии пилота.",
    )
    require(
        re.fullmatch(r"[a-f0-9]{40}", manifest.get("tooling_revision", "")),
        "Нет revision установщика.",
    )
    after = auth.hashes(manifest["new_files"])
    require(
        after == BASE["target_frontend_files"],
        "Нужна точная проверенная сборка интерфейса.",
    )
    require(
        json.loads((bundle / "overall_base.json").read_text()) == BASE,
        "Разные базовые fingerprints пакета.",
    )
    require(
        after.get("index.html")
        and after["index.html"] != BASE["frontend_files"]["index.html"],
        "Нет нового index.",
    )
    expected = auth.hashes(manifest["files"])
    changed = {
        "frontend/" + name
        for name, digest in after.items()
        if BASE["frontend_files"].get(name) != digest
    }
    require(
        set(expected) == HELPERS | {"api/" + name for name in PATCH_FILES} | changed,
        "В пакете есть посторонние файлы.",
    )
    actual = set()
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Ссылка внутри пакета.")
        if path.is_file():
            actual.add(str(path.relative_to(bundle)))
    require(actual == set(expected) | {"overall-manifest.json"}, "Состав пакета изменен.")
    for name, digest in expected.items():
        require(hosted.digest(bundle / name) == digest, "Поврежден файл пакета: " + name)
        if name.startswith("frontend/"):
            require(after[name[9:]] == digest, "Разные checksums frontend.")
    for name, digest in BASE["target_hashes"].items():
        require(expected["api/" + name] == digest, "Неизвестный целевой код: " + name)
    index = (bundle / "frontend/index.html").read_text()
    require(
        'content="white-label-pilot-v1"' in index
        and 'content="noindex, nofollow"' in index,
        "Нужна специальная pilot сборка.",
    )
    return manifest


def save_record(record):
    value = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", value)
    hosted.private_write(RECORD, value)


def load_record():
    require(
        RECORD.is_file() and not RECORD.is_symlink(),
        "Нет известного обновления рейтинга.",
    )
    record = json.loads(RECORD.read_text())
    require(
        record.get("identity") == IDENTITY
        and record.get("release") == BASE["backend_revision"]
        and record.get("frontend_revision") == BASE["frontend_revision"]
        and record.get("phase") in ("prepared", "active", "rolled_back"),
        "Чужое состояние обновления.",
    )
    require(
        re.fullmatch(r"[a-f0-9]{12}", record.get("step", "")),
        "Неизвестный шаг обновления.",
    )
    require(
        record.get("old_name") == hosted.WEB + "-before-" + record["step"],
        "Чужое имя прежнего web.",
    )
    backup = Path(record["backup"])
    require(
        backup.parent == ROOT / "backup"
        and backup.name == "overall-" + record["step"]
        and hosted.owned_path(backup) == backup
        and (ROOT / "backup").resolve() == ROOT / "backup",
        "Чужой backup.",
    )
    require(
        re.fullmatch(r"[a-f0-9]{64}", record.get("old_container_id", "")),
        "Нет ID прежнего web.",
    )
    if record.get("candidate_id"):
        require(
            re.fullmatch(r"[a-f0-9]{64}", record["candidate_id"]),
            "Неизвестный ID кандидата.",
        )
    auth.hashes(record["new_files"])
    for name, item in record["frontend"].items():
        auth.relative_name(name)
        require(
            re.fullmatch(r"[a-f0-9]{64}", item["after"])
            and (item["before"] is None or re.fullmatch(r"[a-f0-9]{64}", item["before"])),
            "Повреждено описание frontend backup.",
        )
    return record


def overlay_args(current, sources):
    result = []
    replaced = {"/procollab/" + name for name in PATCH_FILES}
    for mount in current["Mounts"]:
        if mount["Destination"] in replaced | {"/procollab/pilot-data", "/procollab/log"}:
            continue
        require(
            mount["Type"] == "bind" and not mount["RW"],
            "Неизвестный дополнительный mount.",
        )
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


def app_args(current, environment_file=None):
    result = hosted.container_args(current["Image"], hosted.NETWORK)
    if environment_file is not None:
        result[result.index("--env-file") + 1] = str(hosted.owned_path(environment_file))
    return result


def migration_script(apply):
    return "\n".join(
        [
            "import django,json;django.setup()",
            "from django.db import connection",
            "from django.db.migrations.executor import MigrationExecutor",
            "db=connection.settings_dict",
            f"if not (db['NAME']=={hosted.DB_NAME!r} and db['USER']=={hosted.DB_ROLE!r} "
            "and db['HOST']=='db'): raise RuntimeError('Unexpected pilot database')",
            "with connection.cursor() as cursor:",
            "    cursor.execute(\"SET lock_timeout = '10s'\")",
            "    cursor.execute(\"SET statement_timeout = '120s'\")",
            "    cursor.execute('SET default_transaction_read_only = on')"
            if not apply
            else "    pass",
            "executor=MigrationExecutor(connection)",
            "targets=executor.loader.graph.leaf_nodes()",
            "plan=executor.migration_plan(targets)",
            "if not all(not backwards and "
            f"(m.app_label,m.name)=={MIGRATION!r} for m,backwards in plan): "
            "raise RuntimeError('Unexpected migration plan')",
            "if not all(len(m.operations)==1 and "
            "type(m.operations[0]).__name__=='CreateModel' and "
            "m.operations[0].name=='ProgramQuizOutcome' for m,_ in plan): "
            "raise RuntimeError('Unexpected migration operation')",
            "executor.migrate(targets)" if apply else "# read-only plan",
            "from django.apps import apps" if apply else "# no permission writes",
            "from django.contrib.auth.management import create_permissions"
            if apply
            else "# read-only metadata",
            "create_permissions(apps.get_app_config('partner_programs'), verbosity=0, using=connection.alias)"
            if apply
            else "# no metadata changes",
            "print(json.dumps({'applied':"
            + str(apply)
            + ",'plan':[[m.app_label,m.name] for m,_ in plan]}))",
        ]
    )


def stop_migrator(step, image):
    name = hosted.WEB + "-overall-migrate"
    result = hosted.docker("inspect", name, capture_output=True, text=True, timeout=15)
    if result.returncode:
        return
    container = json.loads(result.stdout)[0]
    labels = container["Config"].get("Labels") or {}
    require(
        container["Image"] == image
        and labels.get(hosted.LABEL) == hosted.IDENTITY
        and labels.get(STEP_LABEL) == step,
        "Имя migrator занято чужим контейнером.",
    )
    hosted.docker(
        "stop",
        "--time",
        "5",
        container["Id"],
        capture_output=True,
        timeout=15,
        check=True,
    )
    hosted.docker(
        "rm", "-f", container["Id"], capture_output=True, timeout=15, check=True
    )


def migrate(current, sources, *, apply, step, environment_file=None, log=None):
    output = (
        {"capture_output": True, "text": True}
        if log is None
        else {"stdout": log, "stderr": hosted.subprocess.STDOUT}
    )
    try:
        result = hosted.docker(
            "run",
            "--rm",
            "--name",
            hosted.WEB + "-overall-migrate",
            "--label",
            STEP_LABEL + "=" + step,
            *overlay_args(current, sources),
            *app_args(current, environment_file),
            "python",
            "-B",
            "-c",
            migration_script(apply),
            timeout=180,
            **output,
        )
    except BaseException:
        stop_migrator(step, current["Image"])
        raise
    require(
        result.returncode == 0,
        "План/миграция рейтинга не прошли проверку; подробности в локальном журнале.",
    )
    return json.loads(result.stdout.splitlines()[-1]) if log is None else None


def case_snapshot(container):
    script = "\n".join(
        [
            "import django,hashlib,json;django.setup()",
            "from partner_programs.models import PartnerProgram,PartnerProgramProject",
            "from partner_programs.services.results import results_data",
            "from users.models import CustomUser",
            "program=PartnerProgram.objects.get(pk=1)",
            "data=results_data(program,{'search':'','case_scope':'all','scope':'all','order':'desc','status':'all'})",
            "data.pop('generated_at')",
            "data['submitted']=list(PartnerProgramProject.objects.filter(partner_program=program)"
            ".order_by('pk').values_list('pk','project_id','submitted'))",
            "data['users_count']=CustomUser.objects.count()",
            "print(json.dumps({'sha256':hashlib.sha256(json.dumps(data,sort_keys=True,default=str)"
            ".encode()).hexdigest(),'scoring_mode':program.evaluation_scoring_mode,"
            "'team_count':len(data['submitted'])}))",
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
        timeout=45,
    )
    require(result.returncode == 0, "Не проверена сохранность оценок кейса.")
    return json.loads(result.stdout.splitlines()[-1])


def check(bundle):
    hosted.scope()
    manifest = verify_bundle(bundle)
    state = hosted.state_read()
    require(
        state["phase"] == "active"
        and state.get("app_patch_revision") == BASE["base_backend_revision"]
        and state.get("weights_revision") == BASE["base_backend_revision"],
        "Нужна известная версия пилота после весов.",
    )
    if RECORD.exists():
        previous = load_record()
        require(
            previous["phase"] == "rolled_back",
            "Есть активное/незавершенное обновление; используйте status или rollback.",
        )
        verify_outside(previous)
    current = hosted.candidate()
    require(
        current and current["State"]["Running"] and current["Image"] == state["image_id"],
        "Работающий пилот не соответствует состоянию.",
    )
    verify_mounts(current)
    weight = json.loads((ROOT / "weights-upgrade.json").read_text())
    require(
        weight.get("identity") == "hosted-v2-weights-upgrade"
        and weight.get("phase") == "active"
        and weight.get("release") == BASE["base_backend_revision"]
        and weight.get("candidate_id") == current["Id"],
        "Не подтверждена установленная версия весов.",
    )
    old_auth = auth.load_record()
    require(
        old_auth["phase"] == "active"
        and old_auth["release"] == BASE["base_frontend_revision"]
        and old_auth["new_files"] == BASE["frontend_files"]
        and old_auth["protected"].get("format") == auth.SNAPSHOT_FORMAT,
        "Не подтверждено исправление входа.",
    )
    expected = old_auth["protected"]["containers"][hosted.WEB]
    require(
        current["Id"] == expected[0]
        and current["Image"] == expected[1]
        and auth.configuration_fingerprint(current) == expected[3],
        "Конфигурация web изменилась после исправления входа.",
    )
    for name in (".env", "state.json", "access.txt", "weights-upgrade.json"):
        path = ROOT / name
        require(
            hosted.digest(path) == old_auth["protected"]["files"].get(str(path)),
            "Изменен защищенный файл: " + name,
        )
    network = hosted.docker_json("network", "inspect", hosted.NETWORK)[0]
    require(
        (network.get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
        and {value["Name"] for value in network.get("Containers", {}).values()}
        <= {hosted.WEB, hosted.PG},
        "В сети пилота есть посторонние контейнеры.",
    )
    require(
        hosted.digest(hosted.ROUTES) == state["new_routes_sha256"]
        and hosted.digest(hosted.MAPS) == state["new_maps_sha256"],
        "Маршруты пилота изменены.",
    )
    verify_runtime(current, updated=False)
    for name, digest in BASE["frontend_files"].items():
        target = auth.frontend_path(name)
        require(
            target.is_file() and hosted.digest(target) == digest,
            "Frontend изменен: " + name,
        )
    for name, digest in manifest["new_files"].items():
        target = auth.frontend_path(name)
        if name not in BASE["frontend_files"] and target.exists():
            require(
                target.is_file() and hosted.digest(target) == digest,
                "Новый путь занят другим файлом.",
            )
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    require(
        int(memory["MemAvailable"].split()[0]) >= 1536 * 1024,
        "Недостаточно RAM с запасом для dev.",
    )
    size = sum((bundle / name).stat().st_size for name in manifest["files"])
    require(
        shutil.disk_usage(ROOT).free >= 2 * 2**30 + 2 * size + 128 * 2**20,
        "Недостаточно диска с запасом для dev.",
    )
    hosted.dev_health()
    auth.api_smoke()
    auth.verify_live(BASE["frontend_files"]["index.html"])
    plan = migrate(current, bundle / "api", apply=False, step=uuid.uuid4().hex[:12])
    if RECORD.exists():
        require(
            container_identity(current) == previous["restored_web"],
            "Прежний web изменен после отката.",
        )
    return state, current, manifest, plan["plan"]


def preserved_configuration(before, after):
    require(after["Image"] == before["Image"], "Образ web изменился.")

    def normalized(container):
        config = dict(container["Config"])
        for name in ("Hostname", "Image"):
            config.pop(name, None)
        # Docker CLI proxy defaults can reorder unique env keys between runs.
        # Duplicate keys retain list order because their effective value may differ.
        environment = config.get("Env") or []
        pairs = [value.split("=", 1) for value in environment]
        if all(len(pair) == 2 for pair in pairs) and len({p[0] for p in pairs}) == len(
            pairs
        ):
            config["Env"] = dict(pairs)
        config["Labels"] = {
            name: value
            for name, value in (config.get("Labels") or {}).items()
            if name not in (files.REVISION_LABEL, STEP_LABEL)
        }
        host = {
            name: value
            for name, value in container["HostConfig"].items()
            if name != "Mounts"
        }
        return {"Config": config, "HostConfig": host}

    require(
        normalized(before) == normalized(after), "Изменились env/лимиты/настройки web."
    )


def verify_replacement_mounts(before, after, sources):
    def items(container):
        result = {
            mount["Destination"]: (mount["Type"], mount["Source"], mount["RW"])
            for mount in container["Mounts"]
        }
        require(len(result) == len(container["Mounts"]), "Повторяющийся mount.")
        return result

    expected = items(before)
    expected.update(
        {
            "/procollab/" + name: ("bind", str(sources / name), False)
            for name in PATCH_FILES
        }
    )
    require(items(after) == expected, "Изменились данные/logs/readonly overlays web.")


def smoke():
    hosted.candidate_health()
    files.email_smoke()
    headers = {
        "Host": "pilot.procollab.ru",
        "X-Forwarded-Proto": "https",
        "Content-Type": "application/json",
    }
    code, _, body = hosted.health(
        "http://127.0.0.1:18319/backend/api/token/",
        headers=headers,
        body=json.dumps(
            {
                "email": "organizer@example.test",
                "password": hosted.environment()["PILOT_ACCOUNT_PASSWORD"],
            }
        ).encode(),
    )
    require(code == 200, "Не прошел вход организатора.")
    headers["Authorization"] = "Bearer " + json.loads(body)["access"]
    url = "http://127.0.0.1:18319/backend/programs/1/management/overall-results/"
    code, _, body = hosted.health(url, headers=headers)
    data = json.loads(body) if code == 200 else {}
    require(
        code == 200
        and data.get("formula") == "case_plus_quiz"
        and (data.get("case_maximum"), data.get("quiz_maximum"), data.get("maximum"))
        == (100, 100, 200),
        "Не прошел API общего рейтинга.",
    )
    code, _, body = hosted.health(url + "export/", headers=headers)
    require(
        code == 200 and body.startswith(b"PK\x03\x04"), "Не прошла выгрузка рейтинга."
    )
    headers.pop("Authorization")
    code, _, _ = hosted.health(url, headers=headers)
    require(code in (401, 403), "Общий рейтинг открыт гостю.")


def wait_for_web():
    for attempt in range(30):
        try:
            auth.api_smoke()
            return
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)


def rollback(record):
    if record["phase"] == "rolled_back":
        return status()
    verify_outside(record)
    stop_migrator(record["step"], record["previous_state"]["image_id"])
    old = hosted.inspect(record["old_container_id"])
    require(
        auth.configuration_fingerprint(old) == record["old_web"][3]
        and old["Image"] == record["old_web"][1],
        "Прежний web изменился; откат остановлен.",
    )
    probe = hosted.docker(
        "container", "inspect", hosted.WEB, capture_output=True, text=True
    )
    current = json.loads(probe.stdout)[0] if probe.returncode == 0 else None
    if current and current["Id"] != record["old_container_id"]:
        labels = current["Config"].get("Labels") or {}
        require(
            labels.get(STEP_LABEL) == record["step"]
            and (
                not record.get("new_web")
                or container_identity(current) == record["new_web"]
            ),
            "Текущий web не принадлежит этому шагу или изменился.",
        )

    def write_rollback(value):
        value["restored_web"] = container_identity(hosted.inspect(hosted.WEB))
        save_record(value)

    result = files.rollback(record, record_writer=write_rollback)
    restored = hosted.candidate()
    require(restored["Id"] == record["old_container_id"], "Не восстановлен прежний web.")
    verify_outside(record)
    record["restored_web"] = container_identity(restored)
    save_record(record)
    auth.verify_live(BASE["frontend_files"]["index.html"])
    return {**result, "schema_retained": True, "nginx_changed": False}


def status():
    hosted.scope()
    record = load_record()
    verify_outside(record)
    current = hosted.candidate()
    if record["phase"] == "prepared":
        return {
            "phase": "prepared",
            "candidate_running": bool(current and current["State"]["Running"]),
            "required_next": "rollback",
        }
    require(current and current["State"]["Running"], "Web пилота не работает.")
    if record["phase"] == "active":
        require(
            container_identity(current) == record["new_web"], "Обновленный web изменился."
        )
        require(hosted.state_read() == record["new_state"], "State пилота изменился.")
        verify_runtime(current, updated=True)
        for name, digest in record["new_files"].items():
            require(
                hosted.digest(auth.frontend_path(name)) == digest,
                "Frontend изменился: " + name,
            )
        auth.verify_live(record["new_files"]["index.html"])
        smoke()
    elif record["phase"] == "rolled_back":
        require(
            container_identity(current) == record["restored_web"],
            "Прежний web изменился после отката.",
        )
        require(
            hosted.state_read() == record["previous_state"],
            "State после отката изменился.",
        )
        verify_runtime(current, updated=False)
        auth.verify_live(BASE["frontend_files"]["index.html"])
    return {
        "phase": record["phase"],
        "overall_revision": record["release"],
        "frontend_revision": record["frontend_revision"]
        if record["phase"] == "active"
        else BASE["base_frontend_revision"],
        "candidate_running": True,
        "dev_http": 200,
        "database_preserved": hosted.DB_NAME,
        "nginx_changed": False,
        "backup": record["backup"],
    }


def apply(bundle):
    if RECORD.exists() and load_record()["phase"] == "active":
        verify_bundle(bundle)
        return status()
    state, current, manifest, _plan = check(bundle)
    progress("Проверки пройдены. Сохраняю БД, интерфейс и настройки пилота.")
    step = uuid.uuid4().hex[:12]
    backup = hosted.owned_path(ROOT / "backup" / ("overall-" + step))
    backup.mkdir(mode=0o700)
    sources = hosted.owned_path(
        ROOT / "releases" / ("overall-" + BASE["backend_revision"]) / "backend"
    )
    for name in PATCH_FILES:
        target = hosted.owned_path(sources / name)
        if target.exists():
            require(
                hosted.digest(target) == BASE["target_hashes"][name],
                "Целевой release изменен.",
            )
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
        "old_web": container_identity(current),
        "previous_state": state,
        "outside": outside_snapshot(current),
        "frontend": {},
        "new_files": manifest["new_files"],
        "case_before": case_snapshot(current),
    }
    for name in sorted(manifest["new_files"], key=lambda value: value == "index.html"):
        target = auth.frontend_path(name)
        before = hosted.digest(target) if target.exists() else None
        after = manifest["new_files"][name]
        if before != after:
            record["frontend"][name] = {"before": before, "after": after}
            if before:
                files.copy_atomic(target, backup / "frontend" / name, mode=0o600)
    files.copy_atomic(ROOT / ".env", backup / "environment.env", mode=0o600)
    files.backup_database(backup)
    save_record(record)
    try:
        verify_outside(record)
        progress(
            "Резервная копия проверена. Применяю только добавочную миграцию 0045.",
        )
        with (backup / "migrations.log").open("ab") as log:
            migrate(
                current,
                sources,
                apply=False,
                step=step,
                environment_file=backup / "environment.env",
                log=log,
            )
            migrate(
                current,
                sources,
                apply=True,
                step=step,
                environment_file=backup / "environment.env",
                log=log,
            )
        verify_outside(record)
        progress("Миграция завершена. Заменяю только web-контейнер пилота.")
        require(
            hosted.docker(
                "rename", hosted.WEB, record["old_name"], capture_output=True
            ).returncode
            == 0,
            "Прежний web не сохранен.",
        )
        require(
            hosted.docker(
                "stop",
                "--time",
                "20",
                record["old_name"],
                capture_output=True,
                timeout=45,
            ).returncode
            == 0,
            "Прежний web не остановлен.",
        )
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
            *overlay_args(current, sources),
            *app_args(current, backup / "environment.env"),
            "daphne",
            "-b",
            "0.0.0.0",
            "-p",
            "8000",
            "--root-path",
            "/backend",
            "procollab.asgi:application",
            capture_output=True,
            text=True,
        )
        require(result.returncode == 0, "Новый web не запущен.")
        record["candidate_id"] = result.stdout.strip()
        save_record(record)
        candidate = hosted.candidate()
        preserved_configuration(current, candidate)
        verify_replacement_mounts(current, candidate, sources)
        record["new_web"] = container_identity(candidate)
        save_record(record)
        wait_for_web()
        verify_runtime(candidate, updated=True)
        smoke()
        require(
            case_snapshot(candidate) == record["case_before"],
            "Оценки, команды или участники изменились; прежний интерфейс сохраняется.",
        )
        verify_outside(record)
        progress(
            "API, регистрация, приглашения, Excel и прежние оценки проверены. Публикую интерфейс.",
        )
        for name in record["frontend"]:
            if name != "index.html":
                files.copy_atomic(bundle / "frontend" / name, auth.frontend_path(name))
        files.copy_atomic(
            bundle / "frontend/index.html", auth.frontend_path("index.html")
        )
        auth.verify_live(manifest["new_files"]["index.html"])
        verify_outside(record)
        new_state = {
            **state,
            "app_patch_revision": record["release"],
            "app_patch_files": {
                **state.get("app_patch_files", {}),
                **BASE["target_hashes"],
            },
            "overall_revision": record["release"],
            "overall_frontend_revision": record["frontend_revision"],
        }
        hosted.state_write(new_state)
        record.update(phase="active", new_state=new_state)
        save_record(record)
        return status()
    except BaseException as error:
        try:
            hosted.private_write(
                backup / "failure.txt", type(error).__name__ + ": " + str(error)
            )
        except OSError:
            pass
        try:
            rollback(record)
        except BaseException as rollback_error:
            raise hosted.Refused(
                "Обновление остановлено; автоматический откат не завершен. Не меняйте БД/контейнеры вручную. Backup: "
                + str(backup)
                + ". Причина: "
                + str(rollback_error)
            ) from error
        raise hosted.Refused(
            "Обновление не прошло проверку; прежние web/UI восстановлены, данные и добавочная схема сохранены. Backup: "
            + str(backup)
        ) from error


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply", "rollback", "status"))
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        with hosted.locked():
            if args.command == "status":
                result = status()
            elif args.command == "rollback":
                hosted.scope()
                result = rollback(load_record())
            else:
                require(args.bundle is not None, "Укажите --bundle.")
                bundle = args.bundle.resolve()
                if args.command == "apply":
                    result = apply(bundle)
                else:
                    _, _, _, plan = check(bundle)
                    result = {
                        "changes_applied": False,
                        "backend_revision": BASE["backend_revision"],
                        "frontend_revision": BASE["frontend_revision"],
                        "migration_count": len(plan),
                        "image_reused": True,
                        "dev_http": 200,
                    }
    except (hosted.Refused, OSError, ValueError) as error:
        sys.exit("ОСТАНОВЛЕНО: " + str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

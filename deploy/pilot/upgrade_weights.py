"""Процентные веса только для действующего hosted-v2, без замены DB/образа/nginx."""

import argparse
import base64
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
import upgrade_invites as files  # noqa: E402

ROOT = hosted.NEW
RECORD = ROOT / "weights-upgrade.json"
BASE = json.loads((Path(__file__).parent / "weights_base.json").read_text())
PATCH_FILES = tuple(BASE["patches"])
IDENTITY = "hosted-v2-weights-upgrade"
MIGRATIONS = {
    ("partner_programs", "0044_partnerprogram_evaluation_scoring_mode"),
    ("project_rates", "0012_criteria_weight_percent_and_more"),
}
require = hosted.require


def save_record(record):
    text = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", text)
    hosted.private_write(RECORD, text)


def load_record():
    record = json.loads(RECORD.read_text())
    require(record.get("identity") == IDENTITY, "Чужое состояние обновления весов.")
    require(
        re.fullmatch(r"[a-f0-9]{40}", record.get("release", "")),
        "Неизвестная revision весов.",
    )
    require(
        re.fullmatch(
            re.escape(hosted.WEB) + r"-before-[a-f0-9]{12}", record.get("old_name", "")
        ),
        "Чужое имя прежнего контейнера.",
    )
    backup = Path(record["backup"])
    require(
        backup.resolve().is_relative_to(ROOT / "backup") and not backup.is_symlink(),
        "Чужой каталог резервной копии.",
    )
    return record


def validate_backend(hashes, manifest):
    for name, expected in {**BASE["patches"], **BASE["protected"]}.items():
        require(hashes.get(name) == expected, "Код пилота изменен: " + name)
    for name, expected in BASE["protected"].items():
        require(
            manifest["files"].get("api/" + name) == expected,
            "Пакет меняет зависимости, профиль или приглашения: " + name,
        )
    require(
        all("api/" + name in manifest["files"] for name in PATCH_FILES),
        "В пакете отсутствуют файлы весов.",
    )
    return {name: manifest["files"]["api/" + name] for name in PATCH_FILES}


def current_fingerprint():
    names = [*BASE["patches"], *BASE["protected"]]
    script = (
        "import hashlib,json;from pathlib import Path;names="
        + json.dumps(names)
        + ";print(json.dumps({n:hashlib.sha256(Path(n).read_bytes()).hexdigest() "
        "if Path(n).is_file() else None for n in names}))"
    )
    result = hosted.docker(
        "exec",
        hosted.WEB,
        "python",
        "-c",
        script,
        capture_output=True,
        text=True,
        timeout=30,
    )
    require(result.returncode == 0, "Не прочитан fingerprint работающего пилота.")
    return json.loads(result.stdout)


def verify_mounts(current):
    mounts = {m["Destination"]: m for m in current["Mounts"]}
    normal = {
        "/procollab/pilot-data": ROOT / "data",
        "/procollab/log": ROOT / "logs",
    }
    require(
        set(mounts) == set(normal) | {"/procollab/" + n for n in files.PATCH_FILES},
        "Неожиданные mounts; существующий контейнер не заменяется.",
    )
    for destination, source in normal.items():
        require(
            mounts[destination]["Source"] == str(source) and mounts[destination]["RW"],
            "Изменен каталог данных пилота.",
        )
    for relative in files.PATCH_FILES:
        mount = mounts["/procollab/" + relative]
        path = hosted.owned_path(mount["Source"])
        require(
            mount["Type"] == "bind"
            and not mount["RW"]
            and path.is_file()
            and hosted.digest(path) == BASE["protected"][relative],
            "Изменено установленное исправление приглашений.",
        )


def dev_snapshot():
    result = {}
    for name in ("api-web-1", "api-redis-1", "api_celery", hosted.OLD_WEB, hosted.DB):
        container = hosted.inspect(name)
        result[name] = [
            container["Id"],
            container["Image"],
            container["State"]["StartedAt"],
        ]
    return result


def verify_outside(record):
    require(
        dev_snapshot() == record["outside"], "Состояние dev/старого пилота изменилось."
    )
    require(
        hosted.digest(hosted.ROUTES) == record["routes"]
        and hosted.digest(hosted.MAPS) == record["maps"],
        "Маршруты nginx изменились снаружи.",
    )
    return hosted.dev_health()


def check(bundle):
    hosted.scope()
    state = hosted.state_read()
    require(state["phase"] == "active", "Нужен действующий hosted-v2.")
    require(
        state.get("app_patch_revision") == BASE["base_app_revision"],
        "Нужна известная версия пилота с исправлением приглашений.",
    )
    if RECORD.exists():
        require(
            load_record()["phase"] == "rolled_back",
            "Есть незавершенное/активное обновление весов.",
        )
    current = hosted.candidate()
    require(
        current and current["State"]["Running"] and current["Image"] == state["image_id"],
        "Работающий пилот не соответствует состоянию.",
    )
    verify_mounts(current)
    old = files.load_record()
    require(
        old["phase"] == "active"
        and old["release"] == BASE["base_app_revision"]
        and old.get("candidate_id") == current["Id"],
        "Не подтверждено установленное исправление приглашений.",
    )
    require(
        hosted.digest(files.frontend_path("index.html"))
        == old["frontend"]["index.html"]["after"],
        "Frontend пилота изменен снаружи.",
    )
    network = hosted.docker_json("network", "inspect", hosted.NETWORK)[0]
    require(
        (network.get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
        and {c["Name"] for c in network.get("Containers", {}).values()}
        <= {hosted.WEB, hosted.PG},
        "В сети пилота есть посторонние контейнеры.",
    )
    require(
        hosted.digest(hosted.ROUTES) == state["new_routes_sha256"]
        and hosted.digest(hosted.MAPS) == state["new_maps_sha256"],
        "Маршруты пилота изменены снаружи.",
    )
    manifest = hosted.verify_bundle(bundle)
    hashes = validate_backend(current_fingerprint(), manifest)
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    require(
        int(memory["MemAvailable"].split()[0]) >= 1536 * 1024,
        "Недостаточно RAM с запасом для dev.",
    )
    require(
        shutil.disk_usage(ROOT).free >= 2 * 2**30 + 256 * 2**20,
        "Недостаточно диска с запасом 2 GiB для dev.",
    )
    hosted.dev_health()
    hosted.candidate_health()
    return state, current, manifest, hashes


def overlay_args(current, sources):
    mounts = []
    for mount in current["Mounts"]:
        if mount["Destination"] in ("/procollab/pilot-data", "/procollab/log"):
            continue
        mounts.extend(
            [
                "--mount",
                f"type=bind,src={mount['Source']},dst={mount['Destination']},readonly",
            ]
        )
    for relative in PATCH_FILES:
        mounts.extend(
            [
                "--mount",
                f"type=bind,src={sources/relative},dst=/procollab/{relative},readonly",
            ]
        )
    return mounts


def migration_script(*, apply):
    # План строится для всех leaves: любой посторонний pending migration блокирует
    # обновление до записи в DB. Старые scores/пользователи не пересоздаются.
    return "\n".join(
        [
            "import django,json; django.setup()",
            "from django.db import connection",
            "from django.db.migrations.executor import MigrationExecutor",
            "db=connection.settings_dict",
            f"if not (db['NAME']=={hosted.DB_NAME!r} and db['USER']=={hosted.DB_ROLE!r} and db['HOST']=='db'): raise RuntimeError('Unexpected pilot database')",
            "with connection.cursor() as cursor:",
            "    cursor.execute(\"SET lock_timeout = '10s'\")",
            "    cursor.execute(\"SET statement_timeout = '120s'\")",
            "executor=MigrationExecutor(connection)",
            "targets=executor.loader.graph.leaf_nodes()",
            "plan=executor.migration_plan(targets)",
            f"allowed={MIGRATIONS!r}",
            "if not all(not backwards and (m.app_label,m.name) in allowed for m,backwards in plan): raise RuntimeError('Unexpected migration plan')",
            "if not all(type(op).__name__ in ('AddField','AddConstraint') for m,_ in plan for op in m.operations): raise RuntimeError('Non-additive migration')",
            "executor.migrate(targets)" if apply else "# read-only plan",
            "print(json.dumps({'applied': "
            + str(apply)
            + ", 'plan': [[m.app_label,m.name] for m,_ in plan]}))",
        ]
    )


def migrate(current, sources, *, apply, log):
    name = hosted.WEB + "-weights-migrate"
    step_label = "io.procollab.pilot.weights.step"
    step = sources.parent.name
    try:
        result = hosted.docker(
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            step_label + "=" + step,
            *overlay_args(current, sources),
            *hosted.container_args(current["Image"], hosted.NETWORK),
            "python",
            "-c",
            migration_script(apply=apply),
            stdout=log,
            stderr=hosted.subprocess.STDOUT,
            timeout=180,
        )
    except BaseException:
        # Завершение docker CLI само по себе не останавливает контейнер. При
        # timeout/Ctrl-C останавливаем только созданный этим шагом migrator.
        probe = hosted.docker("inspect", name, capture_output=True, text=True, timeout=15)
        if probe.returncode == 0:
            container = json.loads(probe.stdout)[0]
            labels = container["Config"].get("Labels") or {}
            require(
                container["Image"] == current["Image"]
                and labels.get(hosted.LABEL) == hosted.IDENTITY
                and labels.get(step_label) == step,
                "Имя migrator занято другим контейнером; он не изменяется.",
            )
            hosted.docker(
                "stop", "--time", "5", container["Id"], capture_output=True, timeout=15
            )
            hosted.docker("rm", "-f", container["Id"], capture_output=True, timeout=15)
        raise
    require(
        result.returncode == 0,
        "Проверка/миграции весов не прошли; подробности в локальном журнале.",
    )


def weighted_program_count():
    pg = hosted.inspect(hosted.PG)
    require(
        (pg["Config"].get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
        and pg["State"]["Running"],
        "Чужой или остановленный PostgreSQL пилота.",
    )

    def scalar(sql):
        result = hosted.docker(
            "exec",
            hosted.PG,
            "sh",
            "-ec",
            'export PGPASSWORD="${POSTGRES_PASSWORD:-}"; exec psql -X -v ON_ERROR_STOP=1 -U pilot_owner -d '
            + hosted.DB_NAME
            + ' -At -c "$1"',
            "pilot-weights",
            sql,
            capture_output=True,
            text=True,
            timeout=30,
        )
        require(result.returncode == 0, "Не проверено состояние весов в БД пилота.")
        return int(result.stdout.strip())

    exists = scalar(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='partner_programs_partnerprogram' AND column_name='evaluation_scoring_mode'"
    )
    return (
        scalar(
            "SELECT COUNT(*) FROM partner_programs_partnerprogram WHERE evaluation_scoring_mode='weighted_percent'"
        )
        if exists
        else 0
    )


def rollback(record):
    require(
        weighted_program_count() == 0,
        "Веса уже включены: прежний API их не понимает. Нужен откат на совместимую версию, данные сохраняются.",
    )
    result = files.rollback(record, record_writer=save_record)
    result.update(schema_retained=True, nginx_changed=False)
    return result


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
    require(code == 200, "Вход организатора не прошел проверку.")
    headers["Authorization"] = "Bearer " + json.loads(body)["access"]
    code, _, body = hosted.health(
        "http://127.0.0.1:18319/backend/programs/1/management/criteria/", headers=headers
    )
    data = json.loads(body) if code == 200 else {}
    require(
        code == 200
        and data.get("scoring_mode") == "legacy"
        and all("weight_percent" in c for c in data.get("criteria", [])),
        "Новый API критериев не прошел проверку; прежний расчет должен сохраняться.",
    )


def apply(bundle):
    state, current, manifest, hashes = check(bundle)
    print("Проверки пройдены. Сохраняю резервную копию БД и frontend пилота.", flush=True)
    identifier = uuid.uuid4().hex[:12]
    backup = hosted.owned_path(ROOT / "backup" / ("weights-" + identifier))
    backup.mkdir(mode=0o700)
    sources = hosted.owned_path(
        ROOT / "releases" / ("weights-" + manifest["api_revision"]) / "backend"
    )
    for relative in PATCH_FILES:
        files.copy_atomic(
            bundle / "api" / relative, hosted.owned_path(sources / relative)
        )
    record = {
        "identity": IDENTITY,
        "release": manifest["api_revision"],
        "phase": "prepared",
        "backup": str(backup),
        "old_container_id": current["Id"],
        "old_name": hosted.WEB + "-before-" + identifier,
        "previous_state": state,
        "frontend": {},
        "outside": dev_snapshot(),
        "routes": hosted.digest(hosted.ROUTES),
        "maps": hosted.digest(hosted.MAPS),
    }
    for source in sorted((bundle / "frontend").rglob("*")):
        if source.is_file():
            relative = str(source.relative_to(bundle / "frontend"))
            target = files.frontend_path(relative)
            before = hosted.digest(target) if target.exists() else None
            after = hosted.digest(source)
            if before != after:
                record["frontend"][relative] = {"before": before, "after": after}
                if before:
                    files.copy_atomic(target, backup / "frontend" / relative, mode=0o600)
    files.backup_database(backup)
    save_record(record)
    print(
        "Резервная копия проверена. Проверяю план и применяю две добавочные миграции.",
        flush=True,
    )
    try:
        with (backup / "migrations.log").open("ab") as log:
            migrate(current, sources, apply=False, log=log)
            migrate(current, sources, apply=True, log=log)
        print("Миграции завершены. Заменяю только web-контейнер пилота.", flush=True)
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
            *overlay_args(current, sources),
            *hosted.container_args(current["Image"], hosted.NETWORK),
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
        require(result.returncode == 0, "Обновленный web не запущен.")
        record["candidate_id"] = result.stdout.strip()
        save_record(record)
        deadline = time.monotonic() + 60
        for attempt in range(30):
            try:
                smoke()
                break
            except Exception:
                if attempt == 29 or time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        print(
            "Вход, регистрация, приглашения и API критериев проверены. Публикую интерфейс.",
            flush=True,
        )
        for relative in record["frontend"]:
            if relative != "index.html":
                files.copy_atomic(
                    bundle / "frontend" / relative, files.frontend_path(relative)
                )
        files.copy_atomic(
            bundle / "frontend/index.html", files.frontend_path("index.html")
        )
        password = (
            (ROOT / "access.txt")
            .read_text()
            .split("Пароль входа: ", 1)[1]
            .splitlines()[0]
        )
        code, _, body = hosted.health(
            hosted.ORIGIN + "/",
            headers={
                "Authorization": "Basic "
                + base64.b64encode(("pilot:" + password).encode()).decode()
            },
        )
        require(
            code == 200
            and hashlib.sha256(body).hexdigest()
            == manifest["files"]["frontend/index.html"],
            "Опубликованный frontend не прошел проверку.",
        )
        verify_outside(record)
        hosted.state_write(
            {
                **state,
                "app_patch_revision": record["release"],
                "app_patch_files": {**state.get("app_patch_files", {}), **hashes},
                "weights_revision": record["release"],
            }
        )
        record["phase"] = "active"
        save_record(record)
    except BaseException as error:
        try:
            hosted.private_write(
                backup / "failure.txt", type(error).__name__ + ": " + str(error)
            )
        except OSError:
            pass
        rollback(record)
        raise hosted.Refused(
            "Обновление не прошло проверку; прежний web/UI восстановлены, данные и добавочная схема сохранены. Журнал: "
            + str(backup)
        )
    return {
        "phase": "active",
        "weights_revision": record["release"],
        "image_reused": True,
        "database_preserved": hosted.DB_NAME,
        "nginx_changed": False,
        "dev_http": 200,
        "backup": str(backup),
        "weights_enabled": False,
    }


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply", "rollback", "status"))
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        with hosted.locked():
            if args.command in ("rollback", "status"):
                hosted.scope()
                record = load_record()
                if args.command == "rollback":
                    result = rollback(record)
                else:
                    current = hosted.candidate()
                    result = {
                        "phase": record["phase"],
                        "weights_revision": record["release"],
                        "candidate_running": bool(
                            current and current["State"]["Running"]
                        ),
                    }
            else:
                require(args.bundle is not None, "Укажите --bundle.")
                if args.command == "apply":
                    result = apply(args.bundle.resolve())
                else:
                    _, _, manifest, _ = check(args.bundle.resolve())
                    result = {
                        "changes_applied": False,
                        "target_revision": manifest["api_revision"],
                        "image_reused": True,
                        "migration_count": 2,
                        "dev_http": 200,
                    }
    except (hosted.Refused, OSError, ValueError) as error:
        sys.exit("ОСТАНОВЛЕНО: " + str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

"""Обновить только hosted-v2: тот же image/DB, четыре readonly Python файла и UI."""

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
from urllib.parse import urlencode
import uuid

sys.dont_write_bytecode = True
import hosted  # noqa: E402

ROOT = hosted.NEW
BASELINE = Path("/root/procollab-pilot-upload-83ca9a9/procollab-pilot")
RECORD = ROOT / "invite-upgrade.json"
REVISION_LABEL = "io.procollab.pilot.app-revision"
PATCH_FILES = (
    "users/filters.py",
    "users/serializers.py",
    "users/views.py",
    "users/white_label_candidates.py",
)
BASE_HASHES = {
    "users/filters.py": "11bc0c29e9fe9c30730fd9007d0e2b8817df4fc1eb18f654400a0ea2e382175f",
    "users/serializers.py": "53de881f56ef3f773784188eef6cf91f035c85f1a2bb7bcc21947d8a64c2f291",
    "users/views.py": "5f4d729d212a4ee48fe78cb940c6b3bbc142db9dcd0a147d5b7995289c43676c",
    "pyproject.toml": "0d9e46cce81c1fd211ae90c73394119d8bb070885f34d9ee2b64d49c6472ffe7",
    "poetry.lock": "fd66c215bc4484d4056bdf9aaa1f31867eda35ccbc2a5e50e223491ecadd3f67",
    "procollab/settings_pilot.py": "9de066782c3ff888f5be3dde0b3f3500377caecf8a1c7a941d1d23646b8038bb",
    "procollab/settings_pilot_inline.py": "6a311d48ee93d7978a6d4e68e5dcf5919023d096b56ee453f67850752ef27366",
    "procollab/white_label.py": "23235bf15e5d7574f86663271b62d0bb739fb4e7e64a3cb366c0d2c2e3488d16",
}
require = hosted.require


def copy_atomic(source, destination, mode=0o644):
    missing = []
    parent = destination.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    public = destination.resolve().is_relative_to(ROOT / "frontend")
    for parent in reversed(missing):
        parent.mkdir(mode=0o755 if public else 0o700)
        parent.chmod(0o755 if public else 0o700)
    temporary = destination.with_name("." + destination.name + ".invite-next")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def frontend_path(relative):
    root = ROOT / "frontend"
    destination = root / relative
    require(
        root.resolve() == root and destination.resolve().is_relative_to(root),
        "Путь выходит за пределы frontend пилота.",
    )
    require(not destination.is_symlink(), "Ссылка вместо frontend файла запрещена.")
    return destination


def validate_backend(hashes, manifest):
    require(
        all(hashes.get(name) == expected for name, expected in BASE_HASHES.items()),
        "Код или зависимости установленного пилота изменены; обновление остановлено.",
    )
    require(
        hashes.get("users/white_label_candidates.py") is None,
        "Модуль поиска уже установлен вне этого обновления.",
    )
    for name, expected in BASE_HASHES.items():
        if name not in PATCH_FILES:
            require(
                manifest["files"].get("api/" + name) == expected,
                "Пакет требует другие зависимости или настройки.",
            )
    require(
        all("api/" + name in manifest["files"] for name in PATCH_FILES),
        "В пакете отсутствует исправление приглашений.",
    )
    return {name: manifest["files"]["api/" + name] for name in PATCH_FILES}


def save_record(record):
    value = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", value)
    hosted.private_write(RECORD, value)


def load_record():
    value = json.loads(RECORD.read_text())
    require(
        value.get("identity") == "hosted-v2-invite-upgrade", "Чужое состояние обновления."
    )
    require(
        re.fullmatch(r"[a-f0-9]{40}", value.get("release", "")),
        "Неизвестная revision обновления.",
    )
    require(
        re.fullmatch(
            re.escape(hosted.WEB) + r"-before-[a-f0-9]{12}", value.get("old_name", "")
        ),
        "Чужое имя сохраненного контейнера.",
    )
    backup = Path(value["backup"])
    require(
        backup.resolve().is_relative_to(ROOT / "backup") and not backup.is_symlink(),
        "Чужой каталог резервной копии.",
    )
    return value


def check(bundle):
    hosted.scope()
    state = hosted.state_read()
    require(state["phase"] == "active", "Нужен активный hosted-v2.")
    require(
        not state.get("app_patch_revision"), "Пилот уже содержит другой source overlay."
    )
    if RECORD.exists():
        require(
            load_record()["phase"] == "rolled_back",
            "Есть активное или незавершенное обновление; сначала проверьте его состояние/rollback.",
        )
    current = hosted.candidate()
    require(
        current and current["State"]["Running"] and current["Image"] == state["image_id"],
        "Работающий пилот не соответствует состоянию.",
    )
    expected_mounts = {
        (str(ROOT / "data"), "/procollab/pilot-data"),
        (str(ROOT / "logs"), "/procollab/log"),
    }
    require(
        {(mount["Source"], mount["Destination"]) for mount in current["Mounts"]}
        == expected_mounts,
        "В пилоте есть другие mounts; они не заменяются.",
    )
    network = hosted.docker_json("network", "inspect", hosted.NETWORK)[0]
    require(
        (network.get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
        and {item["Name"] for item in network.get("Containers", {}).values()}
        <= {hosted.WEB, hosted.PG},
        "В сети пилота есть посторонние ресурсы.",
    )
    require(
        hosted.digest(hosted.ROUTES) == state["new_routes_sha256"]
        and hosted.digest(hosted.MAPS) == state["new_maps_sha256"],
        "Маршруты пилота изменены снаружи.",
    )
    old = hosted.verify_bundle(BASELINE)
    require(
        old["api_revision"] == state["release"],
        "Исходный пакет не соответствует работающему пилоту.",
    )
    manifest = hosted.verify_bundle(bundle)
    script = (
        "import hashlib,json;from pathlib import Path;names="
        + json.dumps([*BASE_HASHES, "users/white_label_candidates.py"])
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
        check=True,
    )
    hashes = validate_backend(json.loads(result.stdout), manifest)
    require(
        hosted.digest(frontend_path("index.html")) == old["files"]["frontend/index.html"],
        "Index установленного пилота изменен снаружи.",
    )
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    require(
        int(memory["MemAvailable"].split()[0]) >= 1536 * 1024,
        "Недостаточно RAM с запасом для dev.",
    )
    require(
        shutil.disk_usage(ROOT).free >= 2 * 2**30 + 192 * 2**20,
        "Недостаточно диска с запасом 2 GiB для dev.",
    )
    hosted.dev_health()
    hosted.candidate_health()
    return state, current, manifest, hashes


def backup_database(backup):
    pg = hosted.inspect(hosted.PG)
    require(
        (pg["Config"].get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
        and pg["State"]["Running"],
        "Чужой или остановленный PostgreSQL пилота.",
    )
    temporary = backup / "database.tmp"
    with temporary.open("xb") as output:
        result = hosted.docker(
            "exec",
            hosted.PG,
            "sh",
            "-ec",
            'export PGPASSWORD="${POSTGRES_PASSWORD:-}"; '
            "exec pg_dump -U pilot_owner -Fc -d procollab_white_label_pilot_v2",
            stdout=output,
            stderr=hosted.subprocess.PIPE,
            timeout=180,
        )
    require(
        result.returncode == 0 and temporary.stat().st_size > 0,
        "Не создана резервная копия БД v2.",
    )
    with temporary.open("rb") as input_file:
        result = hosted.docker(
            "exec",
            "-i",
            hosted.PG,
            "pg_restore",
            "--list",
            stdin=input_file,
            stdout=hosted.subprocess.DEVNULL,
            stderr=hosted.subprocess.PIPE,
            timeout=60,
        )
    require(result.returncode == 0, "Резервная копия v2 не прошла проверку.")
    temporary.rename(backup / "database.dump")


def rollback(record):
    require(record["phase"] in ("prepared", "active"), "Нет обновления для отката.")
    backup = Path(record["backup"])
    # Все внешние изменения проверяются до остановки контейнера или записи файлов.
    for relative, expected in record["frontend"].items():
        target = frontend_path(relative)
        value = hosted.digest(target) if target.exists() else None
        require(
            value in (expected["before"], expected["after"]),
            "Frontend изменен снаружи; откат остановлен.",
        )
        if expected["before"]:
            saved = backup / "frontend" / relative
            require(
                saved.is_file() and hosted.digest(saved) == expected["before"],
                "Резервная копия frontend изменена; откат остановлен.",
            )
    result = hosted.docker(
        "container", "inspect", hosted.WEB, capture_output=True, text=True
    )
    current = json.loads(result.stdout)[0] if result.returncode == 0 else None
    if current:
        require(
            (current["Config"].get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY,
            "Имя пилота занято чужим проектом.",
        )
    if current and current["Id"] != record["old_container_id"]:
        labels = current["Config"].get("Labels") or {}
        require(
            labels.get(REVISION_LABEL) == record["release"]
            and labels.get(hosted.LABEL) == hosted.IDENTITY,
            "Имя пилота занято другим контейнером.",
        )
        require(
            not record.get("candidate_id") or current["Id"] == record["candidate_id"],
            "Кандидат изменен снаружи.",
        )
    old = current
    if not current or current["Id"] != record["old_container_id"]:
        old = hosted.inspect(record["old_name"])
        require(old["Id"] == record["old_container_id"], "Прежний контейнер изменен.")
        require(
            (old["Config"].get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
            and old["Image"] == record["previous_state"]["image_id"],
            "Сохраненный контейнер не принадлежит пилоту.",
        )
    if current and current["Id"] != record["old_container_id"]:
        if current["State"]["Running"]:
            require(
                hosted.docker(
                    "stop", "--time", "20", hosted.WEB, capture_output=True, timeout=45
                ).returncode
                == 0,
                "Кандидат не остановлен.",
            )
        require(
            hosted.docker(
                "rename",
                hosted.WEB,
                hosted.WEB + "-failed-" + current["Id"][:12],
                capture_output=True,
            ).returncode
            == 0,
            "Кандидат не сохранен для анализа.",
        )
        current = None
    if not current:
        require(
            hosted.docker(
                "rename", record["old_name"], hosted.WEB, capture_output=True
            ).returncode
            == 0,
            "Не восстановлено имя прежнего пилота.",
        )
        current = old
    if not current["State"]["Running"]:
        require(
            hosted.docker("start", hosted.WEB, capture_output=True).returncode == 0,
            "Прежний пилот не запущен.",
        )
    for relative, expected in record["frontend"].items():
        if expected["before"]:
            copy_atomic(backup / "frontend" / relative, frontend_path(relative))
    hosted.state_write(record["previous_state"])
    record["phase"] = "rolled_back"
    save_record(record)
    return {
        "phase": "rolled_back",
        "database_restored": False,
        "data_preserved": True,
        "dev_http": hosted.dev_health(),
    }


def email_smoke():
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
                "email": "leader@example.test",
                "password": hosted.environment()["PILOT_ACCOUNT_PASSWORD"],
            }
        ).encode(),
    )
    require(code == 200, "Вход после обновления не прошел smoke.")
    headers["Authorization"] = "Bearer " + json.loads(body)["access"]
    path = "http://127.0.0.1:18319/backend/auth/public-users/?" + urlencode(
        {"fullname": "member@example.test", "partner_program": 1, "user_type": 1}
    )
    code, _, body = hosted.health(path, headers=headers)
    require(
        code == 200
        and [row.get("email") for row in json.loads(body)["results"]]
        == ["member@example.test"],
        "Поиск почты после обновления не прошел smoke.",
    )
    headers.pop("Authorization")
    code, _, body = hosted.health(path, headers=headers)
    require(
        code == 200 and json.loads(body)["count"] == 0,
        "Публичный поиск раскрывает почту.",
    )


def apply(bundle):
    state, current, manifest, hashes = check(bundle)
    release = manifest["api_revision"]
    identifier = uuid.uuid4().hex[:12]
    backup = ROOT / "backup" / ("invite-" + identifier)
    backup.mkdir(mode=0o700)
    sources = ROOT / "releases" / ("invite-" + release) / "backend"
    for relative in PATCH_FILES:
        target = hosted.owned_path(sources / relative)
        copy_atomic(bundle / "api" / relative, target)
    record = {
        "identity": "hosted-v2-invite-upgrade",
        "release": release,
        "phase": "prepared",
        "backup": str(backup),
        "old_container_id": current["Id"],
        "old_name": hosted.WEB + "-before-" + identifier,
        "previous_state": state,
        "frontend": {},
    }
    for source in sorted((bundle / "frontend").rglob("*")):
        if not source.is_file():
            continue
        relative = str(source.relative_to(bundle / "frontend"))
        target = frontend_path(relative)
        before = hosted.digest(target) if target.exists() else None
        after = hosted.digest(source)
        if before != after:
            record["frontend"][relative] = {"before": before, "after": after}
            if before:
                copy_atomic(target, backup / "frontend" / relative, mode=0o600)
    backup_database(backup)
    save_record(record)
    try:
        require(
            hosted.docker(
                "rename", hosted.WEB, record["old_name"], capture_output=True
            ).returncode
            == 0,
            "Прежний пилот не сохранен.",
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
            "Прежний пилот не остановлен.",
        )
        mounts = []
        for relative in PATCH_FILES:
            mounts.extend(
                [
                    "--mount",
                    f"type=bind,src={sources/relative},dst=/procollab/{relative},readonly",
                ]
            )
        args = hosted.container_args(state["image_id"], hosted.NETWORK)
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
            REVISION_LABEL + "=" + release,
            *mounts,
            *args,
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
        require(result.returncode == 0, "Обновленный пилот не запущен.")
        record["candidate_id"] = result.stdout.strip()
        save_record(record)
        for attempt in range(30):
            try:
                hosted.candidate_health()
                break
            except Exception:
                if attempt == 29:
                    raise
                time.sleep(1)
        email_smoke()
        for relative in record["frontend"]:
            if relative != "index.html":
                copy_atomic(bundle / "frontend" / relative, frontend_path(relative))
        copy_atomic(bundle / "frontend/index.html", frontend_path("index.html"))
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
        hosted.dev_health()
        state = {**state, "app_patch_revision": release, "app_patch_files": hashes}
        hosted.state_write(state)
        record["phase"] = "active"
        save_record(record)
    except BaseException:
        rollback(record)
        raise hosted.Refused("Обновление не прошло проверку; прежний пилот восстановлен.")
    return {
        "phase": "active",
        "app_patch_revision": release,
        "image_reused": True,
        "database_preserved": hosted.DB_NAME,
        "nginx_changed": False,
        "dev_http": 200,
        "backup": str(backup),
    }


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply", "rollback"))
    parser.add_argument("--bundle", type=Path)
    arguments = parser.parse_args()
    try:
        with hosted.locked():
            if arguments.command == "rollback":
                hosted.scope()
                result = rollback(load_record())
            else:
                require(arguments.bundle is not None, "Укажите --bundle.")
                if arguments.command == "check":
                    _, _, manifest, _ = check(arguments.bundle.resolve())
                    result = {
                        "changes_applied": False,
                        "target_revision": manifest["api_revision"],
                        "image_reused": True,
                        "dev_http": 200,
                    }
                else:
                    result = apply(arguments.bundle.resolve())
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (
        hosted.Refused,
        OSError,
        ValueError,
        hosted.subprocess.SubprocessError,
    ) as error:
        sys.stderr.write("ОСТАНОВЛЕНО: " + str(error) + "\n")
        raise SystemExit(1)

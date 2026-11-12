"""Заменить только статические файлы авторизации известного пилота, без рестартов."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
import hosted  # noqa: E402
import upgrade_invites as files  # noqa: E402

ROOT = hosted.NEW
RECORD = ROOT / "frontend-upgrade.json"
IDENTITY = "hosted-v2-auth-frontend"
BACKEND = "76570824e596ba06b196171f6cf8be38e5a452d1"
PREVIOUS = "971e52fb1f199ee5c38e2fb42f06ff1946a261a7"
REVISION = "75f41a5d9a008fb97418eb50724b3b99fc8349b7"
BASE_INDEX = "8052cbdedfc44d328fe9d06d90ff1f135cd17506df461e59d582d8d68b73707c"
HELPERS = {"upgrade_frontend.py", "hosted.py", "runtime_import.py", "upgrade_invites.py"}
require = hosted.require


def relative_name(value):
    require(isinstance(value, str), "Неизвестное имя файла.")
    path = PurePosixPath(value)
    require(
        str(path) == value
        and bool(path.parts)
        and not path.is_absolute()
        and all(part not in ("", ".", "..") for part in path.parts)
        and not re.search(r"[\\\x00-\x1f\x7f]", value),
        "Небезопасное имя файла.",
    )
    return value


def frontend_path(relative):
    relative_name(relative)
    target = files.frontend_path(relative)
    require(
        all(
            not parent.is_symlink()
            for parent in target.parents
            if parent.is_relative_to(ROOT / "frontend")
        ),
        "Ссылки внутри frontend запрещены.",
    )
    return target


def hashes(value):
    require(isinstance(value, dict) and value, "Пустой список файлов.")
    for name, digest in value.items():
        relative_name(name)
        require(
            isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest),
            "Некорректный checksum.",
        )
    return value


def verify_bundle(bundle):
    require(
        bundle.resolve() == bundle and not bundle.is_symlink(), "Ссылка вместо пакета."
    )
    manifest = json.loads((bundle / "frontend-manifest.json").read_text())
    require(
        manifest.get("format") == IDENTITY
        and manifest.get("backend_revision") == BACKEND
        and manifest.get("base_frontend_revision") == PREVIOUS
        and manifest.get("frontend_revision") == REVISION,
        "Пакет предназначен для другой версии пилота.",
    )
    before = hashes(manifest["base_files"])
    after = hashes(manifest["new_files"])
    require(before.get("index.html") == BASE_INDEX, "Неизвестная исходная сборка.")
    require(
        after.get("index.html") and after["index.html"] != BASE_INDEX,
        "Нет нового index сборки.",
    )
    expected = hashes(manifest["files"])
    changed = {"frontend/" + p for p, h in after.items() if before.get(p) != h}
    require(set(expected) == HELPERS | changed, "В пакете есть посторонние файлы.")
    actual = set()
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Ссылки в пакете запрещены.")
        if path.is_file():
            actual.add(str(path.relative_to(bundle)))
    require(
        actual == set(expected) | {"frontend-manifest.json"}, "Состав пакета изменен."
    )
    for relative, digest in expected.items():
        require(hosted.digest(bundle / relative) == digest, "Поврежден файл: " + relative)
        if relative.startswith("frontend/"):
            require(after[relative[9:]] == digest, "Несовпадающие checksums frontend.")
    index = (bundle / "frontend/index.html").read_text()
    require(
        'content="white-label-pilot-v1"' in index
        and 'content="noindex, nofollow"' in index,
        "Нужна специальная pilot сборка.",
    )
    return manifest


def protected_snapshot():
    names = (
        "api-web-1",
        "api-redis-1",
        "api_celery",
        hosted.OLD_WEB,
        hosted.DB,
        hosted.WEB,
        hosted.PG,
    )
    result = {"containers": {}, "files": {}}
    for name in names:
        container = hosted.inspect(name)
        require(container["State"]["Running"], "Контейнер не работает: " + name)
        config = {k: container[k] for k in ("Config", "HostConfig", "Mounts")}
        result["containers"][name] = [
            container["Id"],
            container["Image"],
            container["State"]["StartedAt"],
            hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        ]
    paths = [
        ROOT / n for n in ("state.json", ".env", "access.txt", "weights-upgrade.json")
    ]
    paths.extend((hosted.ROUTES, hosted.MAPS))
    for mount in hosted.inspect(hosted.WEB)["Mounts"]:
        if mount["Type"] == "bind" and not mount["RW"]:
            paths.append(hosted.owned_path(mount["Source"]))
    for path in paths:
        require(path.is_file() and not path.is_symlink(), "Неизвестный защищенный файл.")
        result["files"][str(path)] = hosted.digest(path)
    config = subprocess.run(["nginx", "-T"], capture_output=True, check=True)
    result["nginx"] = hashlib.sha256(config.stdout).hexdigest()
    return result


def verify_protected(record):
    require(
        protected_snapshot() == record["protected"],
        "Dev, backend или конфигурация изменились снаружи.",
    )


def api_smoke():
    for url, key, value in (
        ("/backend/instance/", "enabled", True),
        ("/backend/programs/1/registration/", "account_mode", "email_password"),
    ):
        code, _, body = hosted.health(
            "http://127.0.0.1:18319" + url,
            headers={"Host": "pilot.procollab.ru", "X-Forwarded-Proto": "https"},
        )
        require(
            code == 200 and json.loads(body).get(key) == value,
            "API пилота не прошел GET-проверку.",
        )


def verify_live(expected):
    password = (
        (ROOT / "access.txt").read_text().split("Пароль входа: ", 1)[1].splitlines()[0]
    )
    code, _, body = hosted.health(
        hosted.ORIGIN + "/",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(("pilot:" + password).encode()).decode(),
            "Cache-Control": "no-cache",
        },
    )
    require(
        code == 200 and hashlib.sha256(body).hexdigest() == expected,
        "HTTPS отдает другой frontend.",
    )


def save_record(record):
    value = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", value)
    hosted.private_write(RECORD, value)


def load_record():
    require(
        RECORD.is_file() and not RECORD.is_symlink(),
        "Нет известного состояния обновления.",
    )
    record = json.loads(RECORD.read_text())
    require(
        record.get("identity") == IDENTITY
        and record.get("release") == REVISION
        and record.get("phase") in ("prepared", "active", "rolled_back"),
        "Неизвестное состояние frontend.",
    )
    backup = Path(record["backup"])
    require(
        backup.parent == ROOT / "backup"
        and re.fullmatch(r"auth-[a-f0-9]{12}", backup.name)
        and (ROOT / "backup").resolve() == ROOT / "backup"
        and hosted.owned_path(backup) == backup,
        "Чужая резервная копия.",
    )
    hashes(record["new_files"])
    for relative, item in record["frontend"].items():
        relative_name(relative)
        require(
            re.fullmatch(r"[a-f0-9]{64}", item["after"]), "Неверный checksum frontend."
        )
        require(
            item["before"] is None or re.fullmatch(r"[a-f0-9]{64}", item["before"]),
            "Неверный checksum backup.",
        )
    require("index.html" in record["frontend"], "В записи нет index.")
    return record


def check(bundle):
    hosted.scope()
    state = hosted.state_read()
    require(
        state.get("phase") == "active"
        and state.get("app_patch_revision") == BACKEND
        and state.get("weights_revision") == BACKEND,
        "Нужен действующий пилот с установленными весами 7657082.",
    )
    if RECORD.exists():
        require(
            load_record()["phase"] == "rolled_back",
            "Уже есть обновление; сначала проверьте status.",
        )
    current = hosted.candidate()
    weights = json.loads((ROOT / "weights-upgrade.json").read_text())
    require(
        current
        and current["State"]["Running"]
        and current["Image"] == state["image_id"]
        and weights.get("identity") == "hosted-v2-weights-upgrade"
        and weights.get("phase") == "active"
        and weights.get("release") == BACKEND
        and weights.get("candidate_id") == current["Id"],
        "Не подтвержден действующий backend пилота.",
    )
    require(
        hosted.digest(hosted.ROUTES) == state["new_routes_sha256"]
        and hosted.digest(hosted.MAPS) == state["new_maps_sha256"],
        "Маршруты пилота изменены снаружи.",
    )
    manifest = verify_bundle(bundle)
    require(
        (ROOT / "backup").resolve() == ROOT / "backup", "Каталог backup является ссылкой."
    )
    for relative, digest in manifest["base_files"].items():
        target = frontend_path(relative)
        require(
            target.is_file() and hosted.digest(target) == digest,
            "Установленный frontend изменен: " + relative,
        )
    for relative, digest in manifest["new_files"].items():
        target = frontend_path(relative)
        if relative not in manifest["base_files"] and target.exists():
            require(
                target.is_file() and hosted.digest(target) == digest,
                "Новый путь уже занят другим файлом.",
            )
    size = sum(
        (bundle / p).stat().st_size
        for p in manifest["files"]
        if p.startswith("frontend/")
    )
    require(
        shutil.disk_usage(ROOT).free >= 2 * 2**30 + 2 * size,
        "Недостаточно диска с запасом 2 GiB для dev.",
    )
    hosted.dev_health()
    api_smoke()
    return manifest, protected_snapshot()


def rollback(record):
    # Не удаляем новые chunks: уже открытая вкладка может еще запросить их.
    backup = Path(record["backup"])
    for relative, item in record["frontend"].items():
        target = frontend_path(relative)
        current = hosted.digest(target) if target.is_file() else None
        require(
            current in (item["before"], item["after"]),
            "Frontend изменен снаружи; откат остановлен.",
        )
        if item["before"]:
            saved = hosted.owned_path(backup / "frontend" / relative)
            require(
                saved.is_file() and hosted.digest(saved) == item["before"],
                "Резервная копия повреждена.",
            )
    for relative in sorted(record["frontend"], key=lambda p: p == "index.html"):
        if record["frontend"][relative]["before"]:
            files.copy_atomic(backup / "frontend" / relative, frontend_path(relative))
    record["phase"] = "rolled_back"
    save_record(record)
    verify_live(record["frontend"]["index.html"]["before"])


def status():
    hosted.scope()
    record = load_record()
    verify_protected(record)
    hosted.dev_health()
    api_smoke()
    if record["phase"] == "active":
        for relative, digest in record["new_files"].items():
            require(
                hosted.digest(frontend_path(relative)) == digest,
                "Frontend изменен снаружи.",
            )
        verify_live(record["new_files"]["index.html"])
    else:
        verify_live(record["frontend"]["index.html"]["before"])
    return {
        "phase": record["phase"],
        "frontend_revision": REVISION if record["phase"] == "active" else PREVIOUS,
        "dev_http": 200,
        "containers_restarted": False,
        "database_changed": False,
        "nginx_changed": False,
        "backup": record["backup"],
    }


def apply(bundle):
    if RECORD.exists() and load_record()["phase"] == "active":
        return status()
    manifest, protected = check(bundle)
    backup = hosted.owned_path(ROOT / "backup" / ("auth-" + uuid.uuid4().hex[:12]))
    backup.mkdir(mode=0o700)
    record = {
        "identity": IDENTITY,
        "release": REVISION,
        "phase": "prepared",
        "backup": str(backup),
        "protected": protected,
        "frontend": {},
        "new_files": manifest["new_files"],
    }
    for relative, after in manifest["new_files"].items():
        target = frontend_path(relative)
        before = hosted.digest(target) if target.is_file() else None
        if before != after:
            record["frontend"][relative] = {"before": before, "after": after}
            if before:
                saved = backup / "frontend" / relative
                files.copy_atomic(target, saved, mode=0o600)
                require(
                    hosted.digest(saved) == before, "Резервная копия не прошла проверку."
                )
    save_record(record)
    print(  # noqa: T201
        "Проверки пройдены. Резервная копия интерфейса сохранена; публикую только статику пилота.",
        flush=True,
    )
    try:
        verify_protected(record)
        for relative in sorted(record["frontend"], key=lambda p: p == "index.html"):
            source = bundle / "frontend" / relative
            require(
                hosted.digest(source) == record["frontend"][relative]["after"],
                "Пакет изменен во время установки.",
            )
            target = frontend_path(relative)
            before = hosted.digest(target) if target.is_file() else None
            require(
                before == record["frontend"][relative]["before"],
                "Frontend изменен во время установки.",
            )
            files.copy_atomic(source, target)
        verify_live(manifest["new_files"]["index.html"])
        api_smoke()
        verify_protected(record)
        hosted.dev_health()
        record["phase"] = "active"
        save_record(record)
    except BaseException:
        rollback(record)
        raise hosted.Refused(
            "Проверка обновления не прошла; прежний интерфейс пилота восстановлен. Backup: "
            + str(backup)
        )
    return status()


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "apply", "rollback", "status"))
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    try:
        with hosted.locked():
            if args.command in ("check", "apply"):
                require(args.bundle is not None, "Нужен --bundle.")
                if args.command == "apply":
                    result = apply(args.bundle.resolve())
                else:
                    manifest, _ = check(args.bundle.resolve())
                    result = {
                        "changes_applied": False,
                        "target_frontend_revision": REVISION,
                        "dev_http": 200,
                        "containers_restarted": False,
                        "database_changed": False,
                        "nginx_changed": False,
                        "changed_files": len(manifest["files"]) - len(HELPERS),
                    }
            else:
                if args.command == "rollback":
                    hosted.scope()
                    rollback(load_record())
                result = status()
            print(json.dumps(result, ensure_ascii=False, indent=2))  # noqa: T201
    except Exception as error:
        print("ОСТАНОВЛЕНО: " + str(error), file=sys.stderr)  # noqa: T201
        raise SystemExit(1)

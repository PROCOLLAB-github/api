"""Согласованное управление только в hosted-v2: прежняя БД, light и вход без Basic Auth."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlencode
import uuid

sys.dont_write_bytecode = True
import upgrade_overall as overall  # noqa: E402

hosted, auth, files = overall.hosted, overall.auth, overall.files
ROOT = hosted.NEW
BASE = json.loads((Path(__file__).parent / "management_base.json").read_text())
RECORD = ROOT / "management-upgrade.json"
IDENTITY = "hosted-v2-management-upgrade"
STEP_LABEL = "io.procollab.pilot.management.step"
PATCH_FILES = tuple(BASE["target_hashes"])
HELPERS = overall.HELPERS | {"upgrade_management.py", "management_base.json"}
require = hosted.require


def runtime_fingerprint(container):
    names = set(overall.BASE["runtime_hashes"]) | set(PATCH_FILES)
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
        input=json.dumps(sorted(names)),
        capture_output=True,
        text=True,
        timeout=45,
    )
    require(result.returncode == 0, "Не прочитан код пилота.")
    return json.loads(result.stdout)


def verify_runtime(container, *, updated):
    expected = {**overall.BASE["runtime_hashes"], **overall.BASE["target_hashes"]}
    for name in PATCH_FILES:
        expected.setdefault(name, None)
    if updated:
        expected.update(BASE["target_hashes"])
    require(runtime_fingerprint(container) == expected, "Неизвестный код пилота.")


def nginx_outside(config):
    """nginx -T без единственного разрешенного include пилота; остальные блоки побайтно."""
    header = f"# configuration file {hosted.ROUTES}:"
    sections = re.split(r"(?m)(?=^# configuration file )", config)
    owned = [part for part in sections if part.startswith(header + "\n")]
    require(len(owned) == 1, "Нужен один существующий include маршрутов пилота.")
    return "".join(part for part in sections if part not in owned)


def outside_snapshot(current):
    protected = overall.outside_snapshot(current)
    protected["files"].pop(str(hosted.ROUTES))
    protected["files"][str(overall.RECORD)] = hosted.digest(overall.RECORD)
    result = hosted.subprocess.run(
        ["nginx", "-T"], capture_output=True, text=True, check=True
    )
    protected["nginx"] = hashlib.sha256(nginx_outside(result.stdout).encode()).hexdigest()
    network = hosted.docker_json("network", "inspect", hosted.NETWORK)[0]
    require(
        (network.get("Labels") or {}).get(hosted.LABEL) == hosted.IDENTITY
        and {value["Name"] for value in network.get("Containers", {}).values()}
        <= {hosted.WEB, hosted.PG, current["Name"].removeprefix("/")},
        "В сети пилота есть посторонние контейнеры.",
    )
    protected["network"] = {
        name: network.get(name) for name in ("Id", "Driver", "IPAM", "Options", "Labels")
    }
    return protected


def verify_outside(record):
    require(
        outside_snapshot(hosted.inspect(record["old_container_id"])) == record["outside"],
        "Изменились dev, БД, старый пилот или посторонняя конфигурация nginx.",
    )
    return hosted.dev_health()


def public_routes(before):
    replacements = {
        "auth_basic $ppv2_realm;": "auth_basic off;",
        f"auth_basic_user_file {ROOT}/access.htpasswd;\n": "",
        "add_header Set-Cookie $ppv2_gate_cookie;": (
            'add_header Set-Cookie "procollab_pilot_gate=; Path=/; Max-Age=0; '
            'Secure; HttpOnly; SameSite=Strict" always;'
        ),
    }
    for old, new in replacements.items():
        require(before.count(old) == 1, "Неизвестная браузерная защита пилота.")
        before = before.replace(old, new)
    require(
        before.count("auth_basic off;") == 1
        and "auth_basic_user_file" not in before
        and before.count("proxy_set_header Authorization $ppv2_authorization;") == 2,
        "Штатная авторизация API должна сохраниться.",
    )
    return before


def reload_nginx():
    result = hosted.subprocess.run(["nginx", "-t"], capture_output=True, timeout=15)
    require(result.returncode == 0, "Конфигурация nginx не прошла проверку.")
    result = hosted.subprocess.run(
        ["nginx", "-s", "reload"], capture_output=True, timeout=15
    )
    require(result.returncode == 0, "Не выполнена плавная перезагрузка nginx.")


def verify_bundle(bundle):
    require(
        bundle.resolve() == bundle and not bundle.is_symlink(), "Ссылка вместо пакета."
    )
    manifest = json.loads((bundle / "management-manifest.json").read_text())
    require(manifest.get("format") == IDENTITY, "Чужой формат пакета.")
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
        re.fullmatch(r"[a-f0-9]{40}", manifest.get("tooling_revision", "")),
        "Нет версии установщика.",
    )
    require(
        json.loads((bundle / "management_base.json").read_text()) == BASE,
        "Другой baseline пакета.",
    )
    require(
        json.loads((bundle / "overall_base.json").read_text()) == overall.BASE,
        "Другой baseline рейтинга.",
    )
    after = auth.hashes(manifest["new_files"])
    require(
        after == BASE["target_frontend_files"], "Нужна проверенная сборка интерфейса."
    )
    expected = auth.hashes(manifest["files"])
    changed = {
        "frontend/" + n
        for n, value in after.items()
        if BASE["frontend_files"].get(n) != value
    }
    require(
        set(expected) == HELPERS | {"api/" + n for n in PATCH_FILES} | changed,
        "Посторонние файлы в пакете.",
    )
    actual = set()
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Ссылка внутри пакета.")
        if path.is_file():
            actual.add(str(path.relative_to(bundle)))
    require(
        actual == set(expected) | {"management-manifest.json"}, "Изменен состав пакета."
    )
    for name, digest in expected.items():
        require(hosted.digest(bundle / name) == digest, "Поврежден файл: " + name)
        if name.startswith("frontend/"):
            require(after[name[9:]] == digest, "Другой checksum интерфейса.")
    for name, digest in BASE["target_hashes"].items():
        require(expected["api/" + name] == digest, "Другой код: " + name)
    index = (bundle / "frontend/index.html").read_text()
    require(
        'content="white-label-pilot-v1"' in index
        and 'content="noindex, nofollow"' in index
        and 'data-theme="light"' in index,
        "Нужна специальная светлая сборка пилота.",
    )
    return manifest


def save_record(record):
    value = json.dumps(record, ensure_ascii=False, indent=2)
    hosted.private_write(Path(record["backup"]) / "record.json", value)
    hosted.private_write(RECORD, value)


def load_record():
    require(
        RECORD.is_file() and not RECORD.is_symlink(),
        "Нет состояния обновления управления.",
    )
    record = json.loads(RECORD.read_text())
    require(
        record.get("identity") == IDENTITY
        and record.get("release") == BASE["backend_revision"]
        and record.get("frontend_revision") == BASE["frontend_revision"]
        and record.get("phase") in ("prepared", "active", "rolled_back")
        and re.fullmatch(r"[a-f0-9]{12}", record.get("step", "")),
        "Чужое состояние обновления.",
    )
    require(
        record["old_name"] == hosted.WEB + "-before-" + record["step"],
        "Чужое имя прежнего web.",
    )
    backup = Path(record["backup"])
    require(
        backup == ROOT / "backup" / ("management-" + record["step"])
        and hosted.owned_path(backup) == backup,
        "Чужой backup.",
    )
    require(
        re.fullmatch(r"[a-f0-9]{64}", record.get("old_container_id", "")),
        "Неизвестный ID web.",
    )
    auth.hashes(record["new_files"])
    for name, item in record["frontend"].items():
        auth.relative_name(name)
        require(
            re.fullmatch(r"[a-f0-9]{64}", item["after"])
            and (item["before"] is None or re.fullmatch(r"[a-f0-9]{64}", item["before"])),
            "Поврежден frontend backup.",
        )
    return record


def overlay_args(current, sources):
    result = []
    replaced = {"/procollab/" + n for n in PATCH_FILES}
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
    # Нормализация уже проверяет image, env, ресурсы и остальные настройки web.
    cloned = json.loads(json.dumps(after))
    cloned["Config"]["Labels"].pop(STEP_LABEL, None)
    overall.preserved_configuration(before, cloned)

    def mounts(container):
        result = {
            m["Destination"]: (m["Type"], m["Source"], m["RW"])
            for m in container["Mounts"]
        }
        require(len(result) == len(container["Mounts"]), "Повторяющийся mount.")
        return result

    expected = mounts(before)
    expected.update(
        {"/procollab/" + n: ("bind", str(sources / n), False) for n in PATCH_FILES}
    )
    require(mounts(after) == expected, "Изменены данные или посторонние overlays.")


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
    previous = overall.load_record()
    require(previous["phase"] == "active", "Нужен действующий общий рейтинг.")
    overall.verify_outside(previous)
    current = hosted.candidate()
    require(
        current
        and overall.container_identity(current)
        == (restored["restored_web"] if restored else previous["new_web"]),
        "Изменен web рейтинга.",
    )
    require(hosted.state_read() == previous["new_state"], "Изменено состояние пилота.")
    verify_runtime(current, updated=False)
    for name, digest in BASE["frontend_files"].items():
        require(
            hosted.digest(auth.frontend_path(name)) == digest, "Изменен frontend: " + name
        )
    for name, digest in manifest["new_files"].items():
        target = auth.frontend_path(name)
        if name not in BASE["frontend_files"] and target.exists():
            require(
                target.is_file() and hosted.digest(target) == digest,
                "Новый путь уже занят.",
            )
    public_routes(hosted.ROUTES.read_text())
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
    auth.api_smoke()
    auth.verify_live(BASE["frontend_files"]["index.html"])
    plan = hosted.docker(
        "exec",
        current["Id"],
        "python",
        "-B",
        "-c",
        overall.migration_script(False),
        capture_output=True,
        text=True,
        timeout=60,
    )
    require(
        plan.returncode == 0 and json.loads(plan.stdout.splitlines()[-1])["plan"] == [],
        "Найдены неожиданные миграции.",
    )
    return previous["new_state"], current, manifest


def bootstrap_experts(container):
    script = "\n".join(
        [
            "import django,json;django.setup()",
            "from django.db import connection",
            "from django.db.migrations.executor import MigrationExecutor",
            "from partner_programs.services.white_label_experts import "
            "ensure_organizer_experts,organizer_expert_program_id",
            "db=connection.settings_dict",
            f"assert db['NAME']=={hosted.DB_NAME!r} and db['USER']=={hosted.DB_ROLE!r} and db['HOST']=='db'",
            "executor=MigrationExecutor(connection)",
            "assert not executor.migration_plan(executor.loader.graph.leaf_nodes())",
            "assert organizer_expert_program_id()==1",
            "with connection.cursor() as cursor:",
            "    cursor.execute(\"SET lock_timeout = '10s'\")",
            "    cursor.execute(\"SET statement_timeout = '30s'\")",
            "added=ensure_organizer_experts(1)",
            "print(json.dumps({'memberships_added':added,'migration_count':0}))",
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
        timeout=60,
    )
    require(result.returncode == 0, "Не подтверждена подготовка экспертов пилота.")
    return json.loads(result.stdout.splitlines()[-1])


def candidate_search_smoke():
    base = "http://127.0.0.1:18319/backend"
    headers = {
        "Host": "pilot.procollab.ru",
        "X-Forwarded-Proto": "https",
        "Content-Type": "application/json",
    }
    code, _, body = hosted.health(
        base + "/api/token/",
        headers=headers,
        body=json.dumps(
            {
                "email": "leader@example.test",
                "password": hosted.environment()["PILOT_ACCOUNT_PASSWORD"],
            }
        ).encode(),
    )
    require(code == 200, "Не прошел вход участника.")
    tokens = json.loads(body)
    headers["Authorization"] = "Bearer " + tokens["access"]
    path = (
        base
        + "/auth/public-users/?"
        + urlencode(
            {"fullname": "member@example.test", "partner_program": 1, "user_type": 1}
        )
    )
    try:
        code, _, body = hosted.health(path, headers=headers)
        require(
            code == 200
            and [row.get("email") for row in json.loads(body)["results"]]
            == ["member@example.test"],
            "Не прошел поиск участника для приглашения.",
        )
    finally:
        code, _, _ = hosted.health(
            base + "/auth/logout/",
            headers=headers,
            body=json.dumps({"refresh_token": tokens["refresh"]}).encode(),
        )
        require(code == 205, "Не закрыта проверочная сессия участника.")
    headers.pop("Authorization")
    code, _, body = hosted.health(path, headers=headers)
    require(
        code == 200 and json.loads(body)["count"] == 0, "Поиск раскрывает email гостю."
    )


def smoke(*, public=False, index=None):
    auth.api_smoke()
    candidate_search_smoke()
    headers = {
        "Host": "pilot.procollab.ru",
        "X-Forwarded-Proto": "https",
        "Content-Type": "application/json",
    }
    base = "http://127.0.0.1:18319/backend"
    code, _, body = hosted.health(
        base + "/api/token/",
        headers=headers,
        body=json.dumps(
            {
                "email": "organizer@example.test",
                "password": hosted.environment()["PILOT_ACCOUNT_PASSWORD"],
            }
        ).encode(),
    )
    require(code == 200, "Не прошел вход организатора.")
    token = json.loads(body)
    headers["Authorization"] = "Bearer " + token["access"]
    try:
        url = base + "/programs/1/management/overall-results/"
        code, _, body = hosted.health(url, headers=headers)
        data = json.loads(body) if code == 200 else {}
        require(
            code == 200
            and data.get("formula") == "case_plus_quiz"
            and data.get("quiz_maximum") == 100,
            "Не прошел общий рейтинг.",
        )
        require(
            all(
                r["score"] is None
                if not r["ready"]
                else abs(r["score"] - r["case_score"] - r["quiz_score"]) < 0.001
                for r in data["projects"]
            ),
            "Общий итог не равен сумме этапов.",
        )
        code, _, body = hosted.health(url + "export/", headers=headers)
        require(
            code == 200 and body.startswith(b"PK\x03\x04"), "Не прошла выгрузка Excel."
        )
        code, _, body = hosted.health(base + "/evaluation/programs/", headers=headers)
        require(
            code == 200
            and any(
                row["id"] == 1 and row["status"] == "joined"
                for row in json.loads(body)["results"]
            ),
            "Организатор не видит программу в кабинете эксперта.",
        )
        code, _, body = hosted.health(base + "/auth/users/current/", headers=headers)
        require(
            code == 200 and json.loads(body).get("has_evaluation_access") is True,
            "Не подтвержден доступ организатора к оцениванию.",
        )
    finally:
        logout, _, _ = hosted.health(
            base + "/auth/logout/",
            headers=headers,
            body=json.dumps({"refresh_token": token.get("refresh", "")}).encode(),
        )
        require(logout == 205, "Не закрыта проверочная сессия организатора.")
    headers.pop("Authorization")
    code, _, _ = hosted.health(
        base + "/programs/1/management/overall-results/", headers=headers
    )
    require(code in (401, 403), "Рейтинг открыт гостю.")
    if public:
        code, response, body = hosted.health(
            hosted.ORIGIN + "/", headers={"Cache-Control": "no-cache"}
        )
        require(
            code == 200
            and not response.get("WWW-Authenticate")
            and hashlib.sha256(body).hexdigest() == index,
            "Гостевой вход пилота не прошел проверку.",
        )
        code, response, _ = hosted.health(
            hosted.ORIGIN + "/backend/programs/1/management/overall-results/"
        )
        require(
            code in (401, 403)
            and not response.get("WWW-Authenticate", "").startswith("Basic"),
            "Нарушена авторизация API.",
        )
        code, response, body = hosted.health(hosted.ORIGIN + "/backend/admin/")
        require(
            code == 200
            and b'name="username"' in body
            and b'name="password"' in body
            and not response.get("WWW-Authenticate"),
            "Нарушена штатная авторизация admin.",
        )


def rollback(record):
    if record["phase"] == "rolled_back":
        return status()
    verify_outside(record)
    old = hosted.inspect(record["old_container_id"])
    require(
        auth.configuration_fingerprint(old) == record["old_web"][3]
        and old["Image"] == record["old_web"][1],
        "Прежний web изменен снаружи.",
    )
    current = hosted.candidate()
    if current and current["Id"] != record["old_container_id"]:
        require(
            (current["Config"].get("Labels") or {}).get(STEP_LABEL) == record["step"]
            and (
                not record.get("new_web")
                or overall.container_identity(current) == record["new_web"]
            ),
            "Текущий web изменен снаружи.",
        )
    current_routes = hosted.digest(hosted.ROUTES)
    require(
        current_routes in (record["routes_before"], record["routes_after"]),
        "Маршруты изменились снаружи.",
    )
    backup = Path(record["backup"])
    require(
        hosted.digest(backup / "routes.inc") == record["routes_before"],
        "Поврежден backup nginx.",
    )
    # Сначала возвращаем защиту прежнего интерфейса, затем прежний web и статику.
    files.copy_atomic(backup / "routes.inc", hosted.ROUTES, mode=record["routes_mode"])
    reload_nginx()

    def writer(value):
        value["restored_web"] = overall.container_identity(hosted.inspect(hosted.WEB))
        save_record(value)

    result = files.rollback(record, record_writer=writer)
    verify_outside(record)
    auth.verify_live(BASE["frontend_files"]["index.html"])
    return {**result, "expert_memberships_retained": True, "pilot_gate_restored": True}


def status():
    hosted.scope()
    record = load_record()
    verify_outside(record)
    current = hosted.candidate()
    if record["phase"] == "prepared":
        return {"phase": "prepared", "required_next": "rollback"}
    require(current and current["State"]["Running"], "Не работает web пилота.")
    active = record["phase"] == "active"
    require(
        overall.container_identity(current)
        == record["new_web" if active else "restored_web"],
        "Изменился web пилота.",
    )
    require(
        hosted.state_read() == record["new_state" if active else "previous_state"],
        "Изменилось состояние пилота.",
    )
    verify_runtime(current, updated=active)
    expected = record["new_files"] if active else BASE["frontend_files"]
    for name, digest in expected.items():
        require(
            hosted.digest(auth.frontend_path(name)) == digest, "Изменен frontend: " + name
        )
    require(
        hosted.digest(hosted.ROUTES)
        == record["routes_after" if active else "routes_before"],
        "Изменены маршруты пилота.",
    )
    if active:
        smoke(public=True, index=expected["index.html"])
    else:
        auth.verify_live(expected["index.html"])
    return {
        "phase": record["phase"],
        "management_revision": record["release"],
        "frontend_revision": record["frontend_revision"],
        "dev_http": 200,
        "database_preserved": hosted.DB_NAME,
        "migration_count": 0,
        "browser_gate": "disabled" if active else "restored",
        "backup": record["backup"],
    }


def apply(bundle):
    if RECORD.exists():
        verify_bundle(bundle)
        phase = load_record()["phase"]
        if phase == "active":
            return status()
        require(phase == "rolled_back", "Незавершенное обновление: используйте rollback.")
    state, current, manifest = check(bundle)
    overall.progress("Проверки пройдены. Сохраняю БД, интерфейс и include nginx пилота.")
    step = uuid.uuid4().hex[:12]
    backup = hosted.owned_path(ROOT / "backup" / ("management-" + step))
    backup.mkdir(mode=0o700)
    sources = hosted.owned_path(
        ROOT / "releases" / ("management-" + BASE["backend_revision"]) / "backend"
    )
    for name, digest in BASE["target_hashes"].items():
        target = hosted.owned_path(sources / name)
        if target.exists():
            require(hosted.digest(target) == digest, "Изменен целевой release.")
        else:
            files.copy_atomic(bundle / "api" / name, target)
    before = hosted.ROUTES.read_text()
    after = public_routes(before)
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
        "frontend": {},
        "new_files": manifest["new_files"],
        "case_before": overall.case_snapshot(current),
        "routes_before": hosted.digest(hosted.ROUTES),
        "routes_after": hashlib.sha256(after.encode()).hexdigest(),
        "routes_mode": hosted.ROUTES.stat().st_mode & 0o777,
    }
    files.copy_atomic(hosted.ROUTES, backup / "routes.inc", mode=0o600)
    hosted.private_write(backup / "routes-public.inc", after)
    files.copy_atomic(ROOT / ".env", backup / "environment.env", mode=0o600)
    for name in sorted(manifest["new_files"], key=lambda n: n == "index.html"):
        target = auth.frontend_path(name)
        previous = hosted.digest(target) if target.exists() else None
        digest = manifest["new_files"][name]
        if previous != digest:
            record["frontend"][name] = {"before": previous, "after": digest}
            if previous:
                files.copy_atomic(target, backup / "frontend" / name, mode=0o600)
    files.backup_database(backup)
    save_record(record)
    try:
        verify_outside(record)
        overall.progress(
            "Резервная копия проверена. Миграций нет; заменяю только web пилота."
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
            *overall.app_args(current, backup / "environment.env"),
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
            check=True,
        )
        record["candidate_id"] = result.stdout.strip()
        save_record(record)
        candidate = hosted.candidate()
        verify_replacement(current, candidate, sources)
        record["new_web"] = overall.container_identity(candidate)
        save_record(record)
        overall.wait_for_web()
        verify_runtime(candidate, updated=True)
        record["experts"] = bootstrap_experts(candidate)
        smoke()
        require(
            overall.case_snapshot(candidate) == record["case_before"],
            "Изменились оценки, команды или участники.",
        )
        verify_outside(record)
        overall.progress(
            "Расчет и роли проверены. Публикую интерфейс и снимаю Basic Auth только с пилота."
        )
        for name in record["frontend"]:
            if name != "index.html":
                files.copy_atomic(bundle / "frontend" / name, auth.frontend_path(name))
        files.copy_atomic(
            bundle / "frontend/index.html", auth.frontend_path("index.html")
        )
        auth.verify_live(manifest["new_files"]["index.html"])
        files.copy_atomic(
            backup / "routes-public.inc", hosted.ROUTES, mode=record["routes_mode"]
        )
        reload_nginx()
        smoke(public=True, index=manifest["new_files"]["index.html"])
        verify_outside(record)
        new_state = {
            **state,
            "app_patch_revision": record["release"],
            "app_patch_files": {
                **state.get("app_patch_files", {}),
                **BASE["target_hashes"],
            },
            "management_revision": record["release"],
            "management_frontend_revision": record["frontend_revision"],
            "new_routes_sha256": record["routes_after"],
        }
        hosted.state_write(new_state)
        record.update(phase="active", new_state=new_state)
        save_record(record)
        return status()
    except BaseException as error:
        hosted.private_write(
            backup / "failure.txt", type(error).__name__ + ": " + str(error)
        )
        try:
            rollback(record)
        except BaseException as rollback_error:
            raise hosted.Refused(
                "Автоматический откат не завершен. Backup: "
                + str(backup)
                + ". "
                + str(rollback_error)
            ) from error
        raise hosted.Refused(
            "Обновление остановлено; прежние web, интерфейс и защита восстановлены. Backup: "
            + str(backup)
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
                hosted.scope()
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
                        "frontend_revision": BASE["frontend_revision"],
                        "migration_count": 0,
                        "image_reused": True,
                        "dev_http": 200,
                        "pilot_basic_auth_will_be_removed": True,
                    }
    except (hosted.Refused, OSError, ValueError) as error:
        sys.exit("ОСТАНОВЛЕНО: " + str(error))
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

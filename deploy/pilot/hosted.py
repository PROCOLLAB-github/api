"""Этапы обновления только известного пилота. Старые DB/compose/web не изменяются."""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.dont_write_bytecode = True
from runtime_import import (  # noqa: E402
    Refused,
    RuntimeArchive,
    docker,
    docker_json,
    existing_image,
    import_image,
)

OLD = Path("/opt/procollab-white-label-pilot")
NEW = Path("/opt/procollab-white-label-pilot-v2")
PROJECT = "procollab-white-label-pilot"
OLD_WEB = PROJECT + "-web-1"
DB = PROJECT + "-db-1"
WEB = "procollab-white-label-pilot-v2-web"
PG = "procollab-white-label-pilot-v2-db"
NETWORK = "procollab-white-label-pilot-v2"
PG_IMAGE = (
    "postgres@sha256:54e0dd8e8cddcdbb9156c2486eed5a43eccb7214d7c6828097d41ce049fb3984"
)
DB_NAME = "procollab_white_label_pilot_v2"
DB_ROLE = "procollab_pilot_v2"
ROUTES = OLD / "nginx/routes.inc"
MAPS = Path("/etc/nginx/conf.d/procollab-pilot-v2-maps.conf")
ORIGIN = "https://pilot.procollab.ru"
LABEL = "io.procollab.pilot.instance"
IDENTITY = "hosted-v2"
HERE = Path(__file__).resolve().parent


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_write(path, contents):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def state_read():
    require(NEW.resolve() == NEW, "Каталог v2 является ссылкой.")
    value = json.loads((NEW / "state.json").read_text())
    require(
        value.get("identity") == IDENTITY, "Каталог v2 не принадлежит этому установщику."
    )
    return value


def state_write(state):
    private_write(NEW / "state.json", json.dumps(state, ensure_ascii=False, indent=2))


def environment():
    return dict(
        line.split("=", 1)
        for line in (NEW / ".env").read_text().splitlines()
        if "=" in line
    )


def owned_path(path):
    path = Path(path)
    require(
        not path.is_symlink() and path.resolve().is_relative_to(NEW),
        "Путь v2 ведет за пределы нового стенда.",
    )
    return path


def inspect(name):
    return docker_json("container", "inspect", name)[0]


def candidate():
    result = docker("container", "inspect", WEB, capture_output=True, text=True)
    if result.returncode:
        return None
    container = json.loads(result.stdout)[0]
    require(
        (container["Config"].get("Labels") or {}).get(LABEL) == IDENTITY,
        "Имя v2 занято чужим контейнером.",
    )
    ports = container["HostConfig"].get("PortBindings") or {}
    require(
        ports == {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18319"}]},
        "Кандидат использует неожиданный порт.",
    )
    require(
        set(container["NetworkSettings"]["Networks"]) == {NETWORK},
        "Кандидат подключен к другой сети.",
    )
    values = dict(v.split("=", 1) for v in container["Config"].get("Env", []) if "=" in v)
    require(
        values.get("DATABASE_NAME") == DB_NAME and values.get("DATABASE_USER") == DB_ROLE,
        "Кандидат использует другую DB/роль.",
    )
    require(
        values.get("DJANGO_SETTINGS_MODULE") == "procollab.settings_pilot_inline",
        "Кандидат использует другой профиль.",
    )
    return container


def scope():
    require(
        os.geteuid() == 0 and socket.gethostname() == "procollab-dev",
        "Только root на известном procollab-dev.",
    )
    require(
        OLD.resolve() == OLD and ROUTES.resolve().is_relative_to(OLD),
        "Неожиданный путь старого пилота.",
    )
    for name in (OLD_WEB, DB):
        container = inspect(name)
        labels = container["Config"].get("Labels") or {}
        require(
            labels.get("com.docker.compose.project") == PROJECT,
            "Контейнер относится к другому проекту.",
        )
        require(
            labels.get("com.docker.compose.project.working_dir") == str(OLD),
            "Неожиданный compose directory.",
        )
        require(
            container["State"]["Running"], "Старый пилот/DB должен оставаться работающим."
        )
    web = inspect(OLD_WEB)
    bindings = web["NetworkSettings"]["Ports"].get("8000/tcp") or []
    require(
        {(b["HostIp"], b["HostPort"]) for b in bindings} == {("127.0.0.1", "18318")},
        "Неожиданный порт старого пилота.",
    )
    db = inspect(DB)
    names = []
    for name in db["NetworkSettings"]["Networks"]:
        network = docker_json("network", "inspect", name)[0]
        if (network.get("Labels") or {}).get("com.docker.compose.project") == PROJECT:
            members = {v["Name"] for v in network.get("Containers", {}).values()}
            require(
                members <= {OLD_WEB, DB},
                "В сети пилота есть посторонние контейнеры.",
            )
            names.append(name)
    require(len(names) == 1, "Нужна одна отдельная сеть пилота.")
    result = subprocess.run(["nginx", "-T"], capture_output=True, text=True, check=True)
    config = result.stdout
    if not MAPS.exists():
        require("$ppv2_" not in config, "Префикс переменных nginx v2 уже используется.")
    require(
        "include /etc/nginx/conf.d/*.conf;" in config,
        "Нет стандартного include conf.d; основной nginx не изменяется.",
    )
    domains = []
    for match in re.finditer(r"(?m)^\s*server\s*\{", config):
        level, end = 1, match.end()
        while level and end < len(config):
            level += (config[end] == "{") - (config[end] == "}")
            end += 1
        start = match.start()
        block = config[start:end]
        if "include " + str(ROUTES) + ";" in block:
            found = re.search(r"server_name\s+([^;]+);", block)
            require(
                found and found.group(1).split() == ["pilot.procollab.ru"],
                "routes.inc используется другим доменом.",
            )
            domains.append(found.group(1))
    require(domains, "Не найдены vhost пилота.")
    user = re.search(r"(?m)^\s*user\s+(\S+?)(?:\s+(\S+?))?;", config)
    require(user is not None, "Не удалось определить пользователя nginx.")
    group = (
        grp.getgrnam(user.group(2)).gr_gid
        if user.group(2)
        else pwd.getpwnam(user.group(1)).pw_gid
    )
    return {"old_network": names[0], "nginx_gid": group}


def health(url, *, headers=None, body=None):
    request = Request(url, data=body, headers=headers or {})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read(2 * 2**20)
    except HTTPError as error:
        return error.code, dict(error.headers), error.read(2048)


def dev_health():
    for name in (
        "api-web-1",
        "api-redis-1",
        "api_celery",
        "api-react-web-1",
        "api-react-redis-1",
        "api-react-celery",
    ):
        container = inspect(name)
        require(
            container["State"]["Running"],
            "Существующий dev-контейнер не работает: " + name,
        )
        require(
            container["State"].get("Health", {}).get("Status") != "unhealthy",
            "Существующий dev-контейнер unhealthy: " + name,
        )
    code, _, _ = health("https://dev.procollab.ru/")
    require(
        code == 200, "Dev не прошел предварительную HTTP-проверку; изменения остановлены."
    )
    return code


def readiness(runtime):
    target = scope()
    info = docker_json("info", "--format", "{{json .}}")
    require(info["Driver"] == "overlay2", "Неожиданный Docker storage driver.")
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(
        info["Architecture"], info["Architecture"]
    )
    require(
        architecture == runtime.info["architecture"],
        "Архитектура runtime не подходит серверу.",
    )
    require(
        shutil.which("openssl"),
        "Нужен установленный openssl; системные пакеты автоматически не меняются.",
    )
    current = candidate()
    running = bool(current and current["State"]["Running"])
    if not current:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", 18319))
            except OSError:
                raise Refused("Порт 18319 занят другим процессом.")
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    available = int(memory["MemAvailable"].split()[0]) * 1024
    pg_check = docker("container", "inspect", PG, capture_output=True, text=True)
    pg_running = False
    if pg_check.returncode == 0:
        pg = json.loads(pg_check.stdout)[0]
        require(
            (pg["Config"].get("Labels") or {}).get(LABEL) == IDENTITY,
            "Имя PostgreSQL v2 занято.",
        )
        pg_running = pg["State"]["Running"]
    required_memory = 768 + (0 if running else 768) + (0 if pg_running else 256)
    require(
        available >= required_memory * 2**20,
        "Недостаточно RAM с запасом для dev.",
    )
    present = existing_image(runtime)
    required = (
        2 * 2**30 + 512 * 2**20 + (0 if present else runtime.info["image_size_bytes"])
    )
    free = shutil.disk_usage(info["DockerRootDir"]).free
    require(free >= required, "Недостаточно диска: сохраняется минимум 2 GiB для dev.")

    target.update(
        {
            "free_disk_gib": round(free / 2**30, 2),
            "available_ram_mib": round(available / 2**20),
            "dev_http": dev_health(),
            "changes_applied": False,
            "new_containers": [WEB, PG],
            "new_network": NETWORK,
            "new_database": DB_NAME,
            "limits_mib": {"web": 768, "postgres": 256},
        }
    )
    return target


def verify_bundle(bundle):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / "manifest.json").read_text())
    require(
        re.fullmatch(r"[a-f0-9]{40}", manifest.get("api_revision", "")),
        "Нет revision пакета.",
    )
    for relative, expected in manifest["files"].items():
        path = bundle / relative
        require(
            path.resolve().is_relative_to(bundle) and not path.is_symlink(),
            "Небезопасный путь пакета.",
        )
        require(digest(path) == expected, "Checksum пакета не совпадает: " + relative)
    for path in bundle.rglob("*"):
        require(not path.is_symlink(), "Ссылка в пакете запрещена.")
        if path.is_file() and path.name != "manifest.json":
            require(
                str(path.relative_to(bundle)) in manifest["files"],
                "Лишний файл в пакете: " + str(path.relative_to(bundle)),
            )
    require(
        "white-label-pilot-v1" in (bundle / "frontend/index.html").read_text(),
        "Это не pilot frontend.",
    )
    return manifest


def verify_compatibility(bundle, runtime):
    manifest = verify_bundle(bundle)
    require(
        manifest["api_revision"] == runtime.info["api_revision"],
        "Source и runtime взяты из разных сборок. Нужны artifacts одного commit.",
    )
    return manifest


def database_sql(env):
    require(
        env["DATABASE_NAME"] == DB_NAME and env["DATABASE_USER"] == DB_ROLE,
        "Неверная новая DB/роль.",
    )
    password = env["DATABASE_PASSWORD"].replace("'", "''")
    return (
        f'CREATE ROLE "{DB_ROLE}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
        f"NOREPLICATION PASSWORD '{password}';\n"
        f'ALTER DATABASE "{DB_NAME}" OWNER TO "{DB_ROLE}";\n'
        f'REVOKE ALL ON DATABASE "{DB_NAME}" FROM PUBLIC;\n'
        f'ALTER SCHEMA public OWNER TO "{DB_ROLE}";\n'
    )


def prepare_database():
    result = docker("network", "inspect", NETWORK, capture_output=True, text=True)
    if result.returncode:
        require(
            docker(
                "network",
                "create",
                "--label",
                LABEL + "=" + IDENTITY,
                NETWORK,
                capture_output=True,
            ).returncode
            == 0,
            "Новая сеть не создана.",
        )
    else:
        network = json.loads(result.stdout)[0]
        require(
            (network.get("Labels") or {}).get(LABEL) == IDENTITY, "Имя новой сети занято."
        )
        require(
            {c["Name"] for c in network.get("Containers", {}).values()}
            <= {WEB, PG, WEB + "-prepare"},
            "В новой сети есть посторонние контейнеры.",
        )
    private = owned_path(NEW / "pg-private")
    private.mkdir(mode=0o700, exist_ok=True)
    data = owned_path(private / "data")
    data.mkdir(mode=0o700, exist_ok=True)
    if not (private / "postgres.env").exists():
        private_write(
            private / "postgres.env",
            f"POSTGRES_USER=pilot_owner\nPOSTGRES_DB={DB_NAME}\nPOSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n",
        )
    private_write(private / "init.sql", database_sql(environment()))
    os.chown(private / "init.sql", 0, 70)
    (private / "init.sql").chmod(0o640)
    result = docker("container", "inspect", PG, capture_output=True, text=True)
    if result.returncode:
        require(
            docker("pull", PG_IMAGE, capture_output=True, timeout=180).returncode == 0,
            "PostgreSQL image не получен.",
        )
        result = docker(
            "run",
            "-d",
            "--name",
            PG,
            "--restart",
            "unless-stopped",
            "--network",
            NETWORK,
            "--network-alias",
            "db",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "0.25",
            "--pids-limit",
            "128",
            "--oom-score-adj",
            "500",
            "--label",
            LABEL + "=" + IDENTITY,
            "--env-file",
            str(private / "postgres.env"),
            "--mount",
            f"type=bind,src={data},dst=/var/lib/postgresql/data",
            "--mount",
            f"type=bind,src={private/'init.sql'},dst=/docker-entrypoint-initdb.d/10-pilot.sql,readonly",
            "--log-driver",
            "json-file",
            "--log-opt",
            "max-size=10m",
            "--log-opt",
            "max-file=3",
            PG_IMAGE,
            "postgres",
            "-c",
            "shared_buffers=64MB",
            "-c",
            "max_connections=40",
            "-c",
            "work_mem=1MB",
            capture_output=True,
        )
        require(result.returncode == 0, "Новый PostgreSQL не запущен.")
    else:
        pg = json.loads(result.stdout)[0]
        require(
            (pg["Config"].get("Labels") or {}).get(LABEL) == IDENTITY,
            "Имя нового PostgreSQL занято.",
        )
        require(
            pg["Config"]["Image"] == PG_IMAGE, "PostgreSQL v2 использует другой образ."
        )
        require(
            not pg["HostConfig"].get("PortBindings"),
            "У PostgreSQL v2 опубликованы порты.",
        )
        if not pg["State"]["Running"]:
            require(
                docker("start", PG, capture_output=True).returncode == 0,
                "PostgreSQL v2 не запущен.",
            )
    for _ in range(45):
        check = docker(
            "exec",
            PG,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-U",
            "pilot_owner",
            "-d",
            DB_NAME,
            capture_output=True,
        )
        if check.returncode == 0:
            return NETWORK
        time.sleep(1)
    raise Refused(
        "Новый PostgreSQL не прошел readiness; старый пилот продолжает работать."
    )


def backup():
    target = NEW / "backup"
    target.mkdir(mode=0o700, exist_ok=True)
    for source, name in ((ROUTES, "routes.inc"), (OLD / "compose.yml", "compose.yml")):
        if not (target / name).exists():
            private_write(target / name, source.read_text())
    dump = target / "white_label_pilot.dump"
    if not dump.exists():
        temporary = target / "database.tmp"
        command = (
            'export PGPASSWORD="${POSTGRES_PASSWORD:-}"; '
            'exec pg_dump -U "${POSTGRES_USER:-postgres}" -Fc -d white_label_pilot'
        )
        with temporary.open("wb") as stream:
            result = docker(
                "exec",
                DB,
                "sh",
                "-ec",
                command,
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=180,
            )
        require(
            result.returncode == 0 and temporary.stat().st_size > 0,
            "Резервная копия DB не создана.",
        )
        os.replace(temporary, dump)
    with dump.open("rb") as stream:
        check = docker(
            "exec",
            "-i",
            DB,
            "pg_restore",
            "--list",
            stdin=stream,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    require(check.returncode == 0, "Архив DB не прошел pg_restore --list.")


def container_args(image, network):
    return [
        "--network",
        network,
        "--memory",
        "768m",
        "--memory-swap",
        "768m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "256",
        "--oom-score-adj",
        "500",
        "--label",
        LABEL + "=" + IDENTITY,
        "--env-file",
        str(NEW / ".env"),
        "--mount",
        f"type=bind,src={NEW / 'data'},dst=/procollab/pilot-data",
        "--mount",
        f"type=bind,src={NEW / 'logs'},dst=/procollab/log",
        "--log-driver",
        "json-file",
        "--log-opt",
        "max-size=10m",
        "--log-opt",
        "max-file=3",
        image,
    ]


def candidate_health():
    headers = {"Host": "pilot.procollab.ru", "X-Forwarded-Proto": "https"}
    code, _, body = health("http://127.0.0.1:18319/backend/instance/", headers=headers)
    require(
        code == 200 and json.loads(body).get("enabled") is True,
        "Новая версия не прошла instance smoke.",
    )
    code, _, body = health(
        "http://127.0.0.1:18319/backend/programs/1/registration/", headers=headers
    )
    require(
        code == 200 and json.loads(body).get("account_mode") == "email_password",
        "Новая регистрация не прошла smoke.",
    )
    env = environment()
    headers["Content-Type"] = "application/json"
    payload = json.dumps(
        {"email": "leader@example.test", "password": env["PILOT_ACCOUNT_PASSWORD"]}
    ).encode()
    code, _, _ = health(
        "http://127.0.0.1:18319/backend/api/token/", headers=headers, body=payload
    )
    require(code == 200, "Вход синтетического участника не прошел smoke.")


def stage(bundle, runtime):
    manifest = verify_compatibility(bundle, runtime)
    target = readiness(runtime)
    runtime.verify()
    if NEW.exists():
        require(not NEW.is_symlink(), "Каталог v2 является ссылкой.")
        state = state_read()
        require(
            state["release"] == manifest["api_revision"]
            and state["rootfs_sha256"] == runtime.info["archive_sha256"],
            "В v2 уже другая сборка; перезапись запрещена.",
        )
        require(
            state["phase"] != "active", "v2 уже опубликован; stage не перезаписывает его."
        )
    else:
        require(not MAPS.exists(), "Конфигурация maps v2 уже существует без состояния.")
        NEW.mkdir(mode=0o700)
        state = {
            "identity": IDENTITY,
            "release": manifest["api_revision"],
            "rootfs_sha256": runtime.info["archive_sha256"],
            "gate_token": secrets.token_hex(16),
            "original_routes_sha256": digest(ROUTES),
            "phase": "initialized",
        }
        state_write(state)
    require(
        all(not path.is_symlink() for path in NEW.rglob("*")),
        "В каталоге v2 обнаружена ссылка; подготовка остановлена.",
    )
    for relative in (
        "data",
        "data/media",
        "data/static",
        "data/mail",
        "logs",
        "backup",
        "frontend",
        "brand",
        "pg-private",
        "pg-private/data",
        ".env",
        "access.htpasswd",
    ):
        owned_path(NEW / relative)
    if not (NEW / ".env").exists():
        shutil.copy2(Path(bundle) / "nginx.conf.template", NEW / "nginx.conf.template")
        spec = importlib.util.spec_from_file_location(
            "pilot_configure", HERE / "configure.py"
        )
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        config.configure(NEW, ORIGIN)
        env = environment()
        env.update(
            DATABASE_NAME=DB_NAME,
            DATABASE_USER=DB_ROLE,
            DATABASE_HOST="db",
            DATABASE_PORT="5432",
            DJANGO_SETTINGS_MODULE="procollab.settings_pilot_inline",
            DEBUG="False",
        )
        private_write(
            NEW / ".env", "".join(f"{key}={value}\n" for key, value in env.items())
        )
    NEW.chmod(0o711)
    for name in ("frontend", "brand"):
        shutil.copytree(Path(bundle) / name, NEW / name, dirs_exist_ok=True)
        for path in [NEW / name, *(NEW / name).rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
    os.chown(NEW / "access.htpasswd", 0, target["nginx_gid"])
    (NEW / "access.htpasswd").chmod(0o640)
    backup()
    image_id = import_image(runtime, log=NEW / "logs/runtime-import.log")
    network = prepare_database()
    if state["phase"] not in ("staged", "rolled_back"):
        command = (
            "python manage.py check && python manage.py migrate --noinput && "
            "python manage.py collectstatic --noinput && "
            "python manage.py prepare_white_label_pilot"
        )
        with (NEW / "logs/prepare.log").open("ab") as log:
            result = docker(
                "run",
                "--rm",
                "--name",
                WEB + "-prepare",
                *container_args(image_id, network),
                "sh",
                "-ec",
                command,
                stdout=log,
                stderr=log,
                timeout=900,
            )
        require(
            result.returncode == 0,
            "Подготовка новой DB не завершилась; см. logs/prepare.log. Старый пилот работает.",
        )
    current = candidate()
    if current:
        require(current["Image"] == image_id, "Кандидат использует другой образ.")
        if not current["State"]["Running"]:
            require(
                docker("start", WEB, capture_output=True).returncode == 0,
                "Не удалось запустить кандидата.",
            )
    else:
        result = docker(
            "run",
            "-d",
            "--name",
            WEB,
            "--restart",
            "unless-stopped",
            "-p",
            "127.0.0.1:18319:8000",
            *container_args(image_id, network),
            "daphne",
            "-b",
            "0.0.0.0",
            "-p",
            "8000",
            "--root-path",
            "/backend",
            "procollab.asgi:application",
            capture_output=True,
        )
        require(result.returncode == 0, "Кандидат не запущен. Старый пилот работает.")
    for attempt in range(20):
        try:
            candidate_health()
            break
        except Exception:
            if attempt == 19:
                raise Refused("Кандидат не прошел smoke; домен не переключался.")
            time.sleep(1)
    state.update(phase="staged", image_id=image_id)
    state_write(state)
    dev_health()
    return {
        "phase": "staged",
        "candidate_port": 18319,
        "new_database": DB_NAME,
        "old_database": "white_label_pilot",
        "domain_switched": False,
        "backup": str(NEW / "backup"),
    }


def rollback_files(state):
    require(
        digest(ROUTES) in (state["new_routes_sha256"], state["original_routes_sha256"]),
        "routes.inc изменен снаружи; автоматическая перезапись запрещена.",
    )
    if MAPS.exists():
        require(digest(MAPS) == state["new_maps_sha256"], "Файл maps изменен снаружи.")
    if digest(ROUTES) != state["original_routes_sha256"]:
        private_write(ROUTES, (NEW / "backup/routes.inc").read_text())
    if MAPS.exists():
        MAPS.unlink()
    subprocess.run(["nginx", "-t"], check=True, capture_output=True)
    subprocess.run(["nginx", "-s", "reload"], check=True, capture_output=True)
    state["phase"] = "rolled_back"
    state_write(state)


def switch():
    scope()
    state = state_read()
    require(state["phase"] in ("staged", "rolled_back"), "Сначала нужен успешный stage.")
    require(
        digest(ROUTES) == state["original_routes_sha256"] and not MAPS.exists(),
        "Nginx пилота изменился после stage; переключение остановлено.",
    )
    dev_health()
    current = candidate()
    require(
        current and current["State"]["Running"] and current["Image"] == state["image_id"],
        "Кандидат изменился после stage.",
    )
    candidate_health()
    maps = (
        (HERE / "hosted-maps.conf.template")
        .read_text()
        .replace("@@TOKEN@@", state["gate_token"])
    )
    routes = (
        (HERE / "hosted-routes.inc.template").read_text().replace("@@ROOT@@", str(NEW))
    )
    state.update(
        new_maps_sha256=hashlib.sha256(maps.encode()).hexdigest(),
        new_routes_sha256=hashlib.sha256(routes.encode()).hexdigest(),
    )
    state_write(state)
    try:
        private_write(MAPS, maps)
        private_write(ROUTES, routes)
        subprocess.run(["nginx", "-t"], check=True, capture_output=True)
        subprocess.run(["nginx", "-s", "reload"], check=True, capture_output=True)
        time.sleep(1)
        code, _, _ = health(ORIGIN + "/")
        require(code == 401, "Домен не прошел проверку закрытого входа.")
        password = (
            (NEW / "access.txt").read_text().split("Пароль входа: ", 1)[1].splitlines()[0]
        )
        headers = {
            "Authorization": "Basic "
            + base64.b64encode(("pilot:" + password).encode()).decode()
        }
        code, _, body = health(ORIGIN + "/backend/instance/", headers=headers)
        require(
            code == 200 and json.loads(body).get("brand_name") == "Сознание права",
            "Публичный instance smoke не прошел.",
        )
        dev_health()
    except BaseException:
        rollback_files(state)
        raise Refused(
            "Переключение не прошло проверку; маршруты старого пилота восстановлены."
        )
    state["phase"] = "active"
    state_write(state)
    return {
        "phase": "active",
        "origin": ORIGIN,
        "dev_http": 200,
        "old_web_preserved": True,
        "credentials": str(NEW / "access.txt"),
    }


@contextmanager
def locked():
    with Path("/run/lock/procollab-pilot-v2.lock").open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("check", "stage", "switch", "rollback", "status")
    )
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--runtime", type=Path)
    args = parser.parse_args()
    try:
        if args.command in ("check", "stage"):
            require(
                args.bundle is not None and args.runtime is not None,
                "Укажите --bundle и --runtime.",
            )
            runtime = RuntimeArchive(args.runtime)
            if args.command == "check":
                verify_compatibility(args.bundle, runtime)
                result = readiness(runtime)
                runtime.verify()
            else:
                with locked():
                    result = stage(args.bundle, runtime)
        elif args.command == "switch":
            with locked():
                result = switch()
        elif args.command == "rollback":
            with locked():
                scope()
                state = state_read()
                require(state["phase"] == "active", "Нет активного переключения v2.")
                rollback_files(state)
                result = {"phase": "rolled_back", "dev_http": dev_health()}
        else:
            scope()
            state = state_read()
            result = {
                "phase": state["phase"],
                "new_database": DB_NAME,
                "candidate_running": bool(
                    candidate() and candidate()["State"]["Running"]
                ),
            }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (Refused, subprocess.SubprocessError, OSError, ValueError) as error:
        sys.stderr.write("ОСТАНОВЛЕНО: " + str(error) + "\n")
        raise SystemExit(1)

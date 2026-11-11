"""Подтвердить только два новых QA-аккаунта через письма локального пилота."""

import argparse
import base64
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import html
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


ROOT = Path("/opt/procollab-white-label-pilot-v2")
ORIGIN = "https://pilot.procollab.ru"
WEB = "procollab-white-label-pilot-v2-web"
QA_EMAIL = re.compile(r"qa-\d{13}-[a-f0-9]{6}-(?:leader|member)@example\.test")


class Refused(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise Refused(message)


def validate_emails(emails):
    require(
        1 <= len(emails) <= 2
        and len(set(emails)) == len(emails)
        and all(QA_EMAIL.fullmatch(value) for value in emails),
        "Укажите один или два адреса текущего QA-прогона с доменом example.test.",
    )
    runs = {email.rsplit("-", 1)[0] for email in emails}
    require(len(runs) == 1, "Аккаунты относятся к разным QA-прогонам.")


def confirmation_from_mail(directory, recipient):
    for path in sorted(
        directory.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True
    ):
        require(not path.is_symlink(), "Ссылка в каталоге тестовых писем запрещена.")
        if path.stat().st_size > 2 * 2**20:
            continue
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        targets = {
            address.lower() for _, address in getaddresses(message.get_all("To", []))
        }
        if recipient not in targets:
            continue
        for part in message.walk():
            if part.get_content_type() not in ("text/plain", "text/html"):
                continue
            body = html.unescape(part.get_content())
            for url in re.findall(r"https://[^\s<>\"']+", body):
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "pilot.procollab.ru"
                    or parsed.path != "/program-registration/1"
                ):
                    continue
                token = parse_qs(parsed.fragment).get("confirmation", [])
                if len(token) == 1:
                    return token[0]
    raise Refused("Не найдено локальное письмо подтверждения для " + recipient)


class ScopedRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        require(
            urlsplit(newurl).scheme == "https"
            and urlsplit(newurl).netloc == "pilot.procollab.ru",
            "Перенаправление за пределы пилота запрещено.",
        )
        return super().redirect_request(request, fp, code, message, headers, newurl)


def request(opener, path, *, gate, data=None, access=None):
    require(path.startswith("/backend/") and "?" not in path, "Неожиданный путь API.")
    headers = {"Content-Type": "application/json"}
    headers["Authorization"] = (
        "Bearer " + access
        if access
        else "Basic " + base64.b64encode(("pilot:" + gate).encode()).decode()
    )
    body = None if data is None else json.dumps(data).encode()
    try:
        response = opener.open(
            Request(ORIGIN + path, data=body, headers=headers), timeout=30
        )
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read(2 * 2**20))


def confirm(emails):
    validate_emails(emails)
    require(
        os.geteuid() == 0 and socket.gethostname() == "procollab-dev",
        "Только root на известном procollab-dev.",
    )
    require(ROOT.resolve() == ROOT, "Неожиданный путь пилота.")
    state = json.loads((ROOT / "state.json").read_text())
    require(
        state.get("identity") == "hosted-v2" and state.get("phase") == "active",
        "Нужен активный hosted-v2.",
    )
    environment = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if "=" in line
    )
    require(
        environment.get("DATABASE_NAME") == "procollab_white_label_pilot_v2"
        and environment.get("PILOT_EMAIL_DELIVERY") == "file",
        "Нужна отдельная QA-БД и файловая почта.",
    )
    docker_environment = os.environ.copy()
    for key in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        docker_environment.pop(key, None)
    result = subprocess.run(
        ["docker", "--host=unix:///var/run/docker.sock", "container", "inspect", WEB],
        capture_output=True,
        text=True,
        check=True,
        env=docker_environment,
    )
    container = json.loads(result.stdout)[0]
    require(
        (container["Config"].get("Labels") or {}).get("io.procollab.pilot.instance")
        == "hosted-v2",
        "Чужой контейнер.",
    )
    require(container["State"]["Running"], "Пилот не запущен.")
    values = dict(
        value.split("=", 1)
        for value in container["Config"].get("Env", [])
        if "=" in value
    )
    require(
        values.get("DATABASE_NAME") == environment["DATABASE_NAME"],
        "Контейнер использует другую БД.",
    )
    gate = (ROOT / "access.txt").read_text().split("Пароль входа: ", 1)[1].splitlines()[0]
    require(len(gate) >= 16, "Не найден пароль закрытого входа.")
    mail = ROOT / "data/mail"
    require(mail.resolve() == mail, "Неожиданный каталог писем.")
    # Сначала проверяем письма для всех адресов, затем меняем состояние аккаунтов.
    tokens = {email: confirmation_from_mail(mail, email) for email in emails}
    opener = build_opener(ScopedRedirect(), HTTPCookieProcessor(CookieJar()))
    code, instance = request(opener, "/backend/instance/", gate=gate)
    require(
        code == 200
        and instance.get("enabled")
        and instance.get("demo_mode")
        and instance.get("program_id") == 1,
        "Это не демонстрационный экземпляр программы 1.",
    )
    checks = []
    for email in emails:
        code, result = request(
            opener,
            "/backend/programs/1/registration/confirm/",
            gate=gate,
            data={"token": tokens[email]},
        )
        if code == 409 and result.get("code") == "confirmation_used":
            code, result = request(
                opener,
                "/backend/api/token/",
                gate=gate,
                data={"email": email, "password": environment["PILOT_ACCOUNT_PASSWORD"]},
            )
        require(
            code == 200 and result.get("access"),
            "Подтверждение QA-аккаунта не прошло: HTTP " + str(code),
        )
        code, registration = request(
            opener,
            "/backend/programs/1/registration/",
            gate=gate,
            access=result["access"],
        )
        require(
            code == 200
            and registration.get("authenticated")
            and registration.get("enrolled"),
            "Автоматическое участие в программе не подтверждено.",
        )
        checks.append({"email": email, "confirmation_http": 200, "enrolled": True})
    return {"program_id": 1, "checks": checks, "external_email_sent": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", action="append", required=True)
    arguments = parser.parse_args()
    try:
        sys.stdout.write(
            json.dumps(confirm(arguments.email), ensure_ascii=False, indent=2) + "\n"
        )
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        sys.stderr.write("ОСТАНОВЛЕНО: " + str(error) + "\n")
        raise SystemExit(1)

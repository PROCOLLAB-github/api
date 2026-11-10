"""Создать новые локальные настройки пилота. Ничего не меняет в nginx хоста."""

import argparse
import sys
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from urllib.parse import urlsplit


def configure(root: Path, origin: str = "https://pilot.procollab.ru") -> None:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Нужен HTTPS origin без пути и учетных данных.")
    root.mkdir(parents=True, exist_ok=True)
    names = (".env", "nginx.conf", "access.htpasswd", "access.txt")
    if any((root / name).exists() for name in names):
        raise FileExistsError(
            "Настройки уже существуют; повторная подготовка их не перезаписывает."
        )
    if not shutil.which("openssl"):
        raise RuntimeError("Для пароля демо нужен openssl.")
    gate_password = secrets.token_urlsafe(24)
    account_password = secrets.token_urlsafe(24)
    hashed = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=gate_password + "\n",
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    gate_token = secrets.token_hex(32)
    template = (root / "nginx.conf.template").read_text()
    env = {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
        "DATABASE_NAME": "procollab_white_label_pilot",
        "DATABASE_USER": "procollab_pilot",
        "DATABASE_PASSWORD": secrets.token_urlsafe(32),
        "WHITE_LABEL_ENABLED": "True",
        "WHITE_LABEL_PROGRAM_ID": "1",
        "WHITE_LABEL_BRAND_NAME": "Сознание права",
        "WHITE_LABEL_FRONTEND_URL": origin,
        "WHITE_LABEL_API_HOST": parsed.hostname,
        "WHITE_LABEL_LOGO_URL": origin + "/brand/logo.png",
        "WHITE_LABEL_FAVICON_URL": origin + "/brand/favicon.svg",
        "WHITE_LABEL_LOGO_BACKGROUND": "dark",
        "EXPERT_WORKSPACE_FRONTEND_URL": origin,
        "PILOT_ACCOUNT_PASSWORD": account_password,
        "PILOT_EMAIL_DELIVERY": "file",
        "EMAIL_USER": "pilot@example.test",
        "AUTOPOSTING_ON": "False",
    }
    files = {
        ".env": "".join(f"{key}={value}\n" for key, value in env.items()),
        "nginx.conf": template.replace("@@GATE_TOKEN@@", gate_token),
        "access.htpasswd": "pilot:" + hashed + "\n",
        "access.txt": (
            "Только для владельца стенда. Не публиковать и не добавлять в git.\n"
            f"Демо: {origin}\nВнешний вход: pilot\nПароль входа: {gate_password}\n"
            f"Пароль синтетических аккаунтов example.test: {account_password}\n"
            "Аккаунты: admin, organizer, expert, leader, member @example.test\n"
            "Админка: /backend/admin/\nПисьма сохраняются в data/mail, наружу не отправляются.\n"
        ),
    }
    created = []
    try:
        for name, contents in files.items():
            path = root / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "w") as stream:
                stream.write(contents)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    # nginx читает только публичные файлы. Не зависим от umask владельца
    # архива и не открываем каталог с письмами и логами.
    for folder, mode in (
        ("data", 0o711),
        ("data/media", 0o755),
        ("data/static", 0o755),
        ("data/mail", 0o700),
        ("logs", 0o700),
    ):
        path = root / folder
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
    sys.stdout.write(
        "Настройки созданы. Данные входа — в локальном access.txt с правами 0600.\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--origin", default="https://pilot.procollab.ru")
    args = parser.parse_args()
    configure(args.root, args.origin)

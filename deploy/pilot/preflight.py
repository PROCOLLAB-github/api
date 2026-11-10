"""Read-only проверка сервера перед установкой нового пилота."""

from pathlib import Path
import shutil
import argparse
import os
import sys
import socket
import subprocess


def report(*parts):
    sys.stdout.write(" ".join(str(part) for part in parts) + "\n")


def run(argv):
    environment = os.environ.copy()
    if argv[0] == "docker":
        for name in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environment.pop(name, None)
        argv = ["docker", "--host=unix:///var/run/docker.sock", *argv[1:]]
    result = subprocess.run(
        argv, text=True, capture_output=True, timeout=20, env=environment
    )
    return result.returncode, result.stdout


def main(check=False):
    failures = []
    report("DNS pilot.procollab.ru:", socket.gethostbyname("pilot.procollab.ru"))
    for command in ("docker", "nginx", "openssl", "certbot"):
        report(command + ":", shutil.which(command) or "не найден")
    free_gib = shutil.disk_usage(Path.cwd()).free / 2**30
    report("Свободно на диске, GiB:", round(free_gib, 1))
    if free_gib < 8:
        failures.append("Нужно минимум 8 GiB свободного диска перед запуском.")
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0])
    available_mib = memory["MemAvailable"] / 1024
    report("Доступная память, MiB:", round(available_mib))
    if available_mib < 2560:
        failures.append("Нужно минимум 2560 MiB доступной памяти с запасом для dev.")
    own_gateway = False
    if shutil.which("docker"):
        code, output = run(["docker", "ps", "--format", "{{.Names}} {{.Ports}}"])
        report(
            "Существующие контейнеры:\n" + output
            if code == 0
            else "Нет доступа к локальному Docker"
        )
        if code:
            failures.append("Нет доступа к локальному Docker.")
        if "procollab-white-label-pilot-" in output:
            failures.append(
                "Уже есть hosted pilot: второй полный стек не устанавливается."
            )
        code, own = run(
            [
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.project=procollab-pilot",
                "--filter",
                "label=com.docker.compose.service=gateway",
                "--format",
                "{{.Ports}}",
            ]
        )
        own_gateway = code == 0 and "127.0.0.1:18081->80/tcp" in own
    else:
        failures.append("Docker не установлен.")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 18081))
            report("Порт 18081: свободен")
        except OSError:
            report(
                "Порт 18081:",
                "занят этим пилотом" if own_gateway else "занят другим процессом",
            )
            if not own_gateway:
                failures.append("Порт 18081 занят другим процессом.")
    if shutil.which("nginx"):
        code, output = run(["nginx", "-T"])
        if code and shutil.which("sudo"):
            code, output = run(["sudo", "-n", "nginx", "-T"])
        # Конфигурация может содержать пароли; выводим только server_name.
        matches = [
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith("server_name ") and "pilot.procollab.ru" in line
        ]
        report(
            "Текущие server_name pilot:\n" + "\n".join(matches)
            if code == 0
            else "Для nginx -T нужен доступ владельца конфигурации"
        )
    for failure in failures:
        report("НЕ ГОТОВО:", failure)
    report("Preflight завершен без изменений на сервере.")
    return 1 if check and failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.check))

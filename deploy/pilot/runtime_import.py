"""Поточный импорт rootfs: без второй распаковки многослойного docker save."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile


class Refused(RuntimeError):
    pass


def docker(*args, **kwargs):
    environment = os.environ.copy()
    for key in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(key, None)
    return subprocess.run(
        ["docker", "--host=unix:///var/run/docker.sock", *args],
        env=environment,
        **kwargs,
    )


def docker_json(*args):
    result = docker(*args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise Refused("Локальный Docker не выполнил проверку.")
    return json.loads(result.stdout)


class RuntimeArchive:
    def __init__(self, path):
        self.path = Path(path)
        with self.open("runtime.json") as stream:
            self.info = json.load(stream)
        meta = self.info
        if (
            meta.get("format") != "docker-export-v1"
            or not re.fullmatch(r"[a-f0-9]{40}", meta.get("api_revision", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", meta.get("archive_sha256", ""))
            or not re.fullmatch(
                r"procollab-white-label-pilot-api:[a-f0-9]{12}", meta.get("image", "")
            )
            or type(meta.get("image_size_bytes")) is not int
            or meta["image_size_bytes"] <= 0
        ):
            raise Refused("Некорректные метаданные runtime artifact.")

    @contextmanager
    def open(self, member):
        if member not in ("runtime.json", "pilot-api-rootfs.tar.gz"):
            raise Refused("Неизвестный файл runtime.")
        if self.path.is_dir():
            if member == "runtime.json" and (self.path / member).stat().st_size > 2**20:
                raise Refused("Метаданные runtime превышают допустимый размер.")
            with (self.path / member).open("rb") as stream:
                yield stream
        else:
            with zipfile.ZipFile(self.path) as archive:
                if (
                    member == "runtime.json"
                    and archive.getinfo(member).file_size > 2**20
                ):
                    raise Refused("Метаданные runtime превышают допустимый размер.")
                with archive.open(member) as stream:
                    yield stream

    def verify(self):
        digest = hashlib.sha256()
        with self.open("pilot-api-rootfs.tar.gz") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != self.info["archive_sha256"]:
            raise Refused("Checksum runtime не совпадает. Импорт не выполнялся.")


def changes(meta):
    config = meta["config"]
    if config.get("Volumes") or config.get("Healthcheck"):
        raise Refused("Этот exporter не поддерживает VOLUME/HEALTHCHECK.")
    result = []
    for value in config.get("Env") or []:
        key, separator, contents = value.partition("=")
        if (
            not separator
            or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key)
            or any(c in contents for c in "\n\r\x00$`")
        ):
            raise Refused("Неподдерживаемое значение ENV образа.")
        result.append("ENV " + key + "=" + json.dumps(contents))
    for name, value in (
        ("WORKDIR", config.get("WorkingDir")),
        ("USER", config.get("User")),
    ):
        if value:
            if not re.fullmatch(r"[A-Za-z0-9_/:.\-]+", value):
                raise Refused("Неподдерживаемая конфигурация образа.")
            result.append(name + " " + value)
    for name in ("Entrypoint", "Cmd"):
        value = config.get(name)
        if value:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise Refused("Неверная команда образа.")
            result.append(name.upper() + " " + json.dumps(value))
    result.extend(
        [
            'LABEL org.opencontainers.image.revision="' + meta["api_revision"] + '"',
            'LABEL io.procollab.pilot.rootfs-sha256="' + meta["archive_sha256"] + '"',
        ]
    )
    return result


def existing_image(runtime):
    result = docker(
        "image", "inspect", runtime.info["image"], capture_output=True, text=True
    )
    if result.returncode:
        return None
    image = json.loads(result.stdout)[0]
    labels = image["Config"].get("Labels") or {}
    if labels.get("io.procollab.pilot.rootfs-sha256") != runtime.info["archive_sha256"]:
        raise Refused("Тег образа уже занят другой сборкой; он не перезаписывается.")
    return image["Id"]


def import_image(runtime, *, log, throttle=True):
    present = existing_image(runtime)
    if present:
        return present
    runtime.verify()
    info = docker_json("info", "--format", "{{json .}}")
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(
        info["Architecture"], info["Architecture"]
    )
    if runtime.info["architecture"] != architecture:
        raise Refused("Архитектура образа не соответствует серверу.")
    if (
        shutil.disk_usage(info["DockerRootDir"]).free
        < runtime.info["image_size_bytes"] + 2 * 2**30
    ):
        raise Refused("Для импорта не хватает диска с запасом 2 GiB для dev.")
    args = []
    for change in changes(runtime.info):
        args.extend(["--change", change])
    environment = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
    }
    with runtime.open("pilot-api-rootfs.tar.gz") as stream, Path(log).open(
        "wb"
    ) as errors:
        process = subprocess.Popen(
            [
                "docker",
                "--host=unix:///var/run/docker.sock",
                "import",
                *args,
                "-",
                runtime.info["image"],
            ],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
        )
        started, copied = time.monotonic(), 0
        try:
            for chunk in iter(lambda: stream.read(512 * 1024), b""):
                process.stdin.write(chunk)
                copied += len(chunk)
                if throttle:
                    delay = copied / (8 * 2**20) - (time.monotonic() - started)
                    if delay > 0:
                        time.sleep(min(delay, 0.1))
            process.stdin.close()
            output = process.stdout.read()
            if process.wait(timeout=600) or not re.fullmatch(
                rb"sha256:[a-f0-9]{64}\s*", output
            ):
                raise Refused(
                    "Импорт не завершился; подробности в локальном runtime-import.log."
                )
        except BaseException:
            process.kill()
            process.wait()
            raise
    return existing_image(runtime)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    arguments = parser.parse_args()
    image_id = import_image(
        RuntimeArchive(arguments.runtime), log="runtime-import.log", throttle=False
    )
    sys.stdout.write("Runtime image imported: " + image_id + "\n")

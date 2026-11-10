"""Распаковать только source/frontend artifact в новый каталог владельца."""

import argparse
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import zipfile


def unpack(source, destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("Каталог уже существует; перезапись запрещена.")
    destination.mkdir(mode=0o700, parents=True)
    total = 0
    with zipfile.ZipFile(source) as archive:
        if archive.namelist() != ["procollab-pilot.tar.gz"]:
            raise ValueError("Нужен artifact procollab-pilot-candidate.")
        with archive.open("procollab-pilot.tar.gz") as stream:
            with tarfile.open(fileobj=stream, mode="r|gz") as contents:
                for member in contents:
                    path = PurePosixPath(member.name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not path.parts
                        or path.parts[0] != "procollab-pilot"
                    ):
                        raise ValueError("Небезопасный путь архива.")
                    target = destination.joinpath(*path.parts)
                    if member.isdir():
                        target.mkdir(mode=0o755, parents=True, exist_ok=True)
                    elif member.isfile():
                        total += member.size
                        if total > 256 * 2**20 or member.size > 64 * 2**20:
                            raise ValueError("Пакет превышает допустимый размер.")
                        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                        with target.open("xb") as output, contents.extractfile(
                            member
                        ) as data:
                            shutil.copyfileobj(data, output, length=1024 * 1024)
                        target.chmod(member.mode & 0o755)
                    else:
                        raise ValueError("Ссылки и специальные файлы запрещены.")
    return destination / "procollab-pilot"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(unpack(args.zip, args.destination))  # noqa: T201

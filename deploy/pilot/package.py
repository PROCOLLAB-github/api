"""Собрать переносимый пилот из отслеживаемого API и pilot Angular build."""

import argparse
import sys
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


def package(api: Path, frontend: Path, target: Path) -> Path:
    if target.exists():
        raise FileExistsError("Каталог пакета уже существует.")
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=api
    ).strip():
        raise ValueError("Сначала проверьте и зафиксируйте изменения API в git.")
    if not (frontend / "index.html").is_file():
        raise ValueError("Не найдена Angular сборка.")
    if "white-label-pilot-v1" not in (frontend / "index.html").read_text():
        raise ValueError(
            "Нужна специальная pilot сборка, обычная сборка использует основной API."
        )
    source = Path(__file__).resolve().parent
    target.mkdir(parents=True)
    for name in (
        "compose.yml",
        "nginx.conf.template",
        "host-nginx.conf.example",
        "configure.py",
        "pilotctl",
        "preflight.py",
        "hosted.py",
        "upgrade_invites.py",
        "runtime_import.py",
        "hosted-maps.conf.template",
        "hosted-routes.inc.template",
        "README.md",
    ):
        shutil.copy2(source / name, target / name)
    (target / "pilotctl").chmod(0o750)
    shutil.copytree(frontend, target / "frontend")
    shutil.copytree(source / "brand", target / "brand")
    # В Cloud build assets могут иметь 0600/0700. Nginx worker читает только
    # эти публичные каталоги; секреты и API source здесь не затрагиваются.
    for public in (target / "frontend", target / "brand"):
        public.chmod(0o755)
        for path in public.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "-z"],
            cwd=api,
        )
        .decode()
        .split("\0")
    )
    if "procollab/settings_pilot.py" not in tracked:
        raise ValueError("Сначала добавьте и проверьте API pilot profile в git.")
    for relative in filter(None, tracked):
        path = api / relative
        if path.is_symlink():
            raise ValueError(f"Символическая ссылка не входит в пакет: {relative}")
        destination = target / "api" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=api, text=True
    ).strip()
    manifest = {"api_revision": revision, "files": {}}
    for path in sorted(target.rglob("*")):
        if path.is_file():
            manifest["files"][str(path.relative_to(target))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    archive = target.with_suffix(".tar.gz")
    with tarfile.open(archive, "x:gz") as tar:
        tar.add(target, arcname=target.name)
    archive.chmod(0o600)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(
        str(package(args.api.resolve(), args.frontend.resolve(), args.target.resolve()))
        + "\n"
    )

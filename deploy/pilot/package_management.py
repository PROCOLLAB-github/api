"""Пакет согласованного управления для существующего пилота после общего рейтинга."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

import upgrade_management as upgrade

SOURCE = Path(__file__).resolve().parent


def tooling_revision():
    repo = SOURCE.parents[1]
    require = upgrade.require
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo
        ).strip(),
        "Сначала проверьте и зафиксируйте изменения установщика.",
    )
    subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            *["deploy/pilot/" + name for name in upgrade.HELPERS],
            "deploy/pilot/package_management.py",
        ],
        cwd=repo,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def package(api, frontend, output):
    upgrade.require(not output.exists(), "Каталог пакета уже существует.")
    revision = tooling_revision()
    for name, digest in upgrade.BASE["target_hashes"].items():
        source = api / name
        upgrade.require(
            source.is_file()
            and not source.is_symlink()
            and upgrade.hosted.digest(source) == digest,
            "Неизвестный runtime файл: " + name,
        )
    after = {}
    for path in sorted(frontend.rglob("*")):
        upgrade.require(not path.is_symlink(), "Ссылка в frontend build.")
        if path.is_file():
            after[str(path.relative_to(frontend))] = upgrade.hosted.digest(path)
    upgrade.auth.hashes(after)
    output.mkdir(mode=0o700, parents=True)
    bundle = output / "procollab-pilot"
    bundle.mkdir(mode=0o755)
    for name in upgrade.HELPERS:
        if name == "management_base.json":
            (bundle / name).write_text(
                json.dumps(upgrade.BASE, ensure_ascii=False, indent=2) + "\n"
            )
        else:
            shutil.copyfile(SOURCE / name, bundle / name)
    for name in upgrade.PATCH_FILES:
        target = bundle / "api" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(api / name, target)
    for name, digest in after.items():
        if upgrade.BASE["frontend_files"].get(name) != digest:
            target = bundle / "frontend" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(frontend / name, target)
    manifest = {
        "format": upgrade.IDENTITY,
        "base_backend_revision": upgrade.BASE["base_backend_revision"],
        "base_frontend_revision": upgrade.BASE["base_frontend_revision"],
        "backend_revision": upgrade.BASE["backend_revision"],
        "frontend_revision": upgrade.BASE["frontend_revision"],
        "tooling_revision": revision,
        "new_files": after,
        "files": {
            str(path.relative_to(bundle)): upgrade.hosted.digest(path)
            for path in sorted(bundle.rglob("*"))
            if path.is_file()
        },
    }
    (bundle / "management-manifest.json").write_text(json.dumps(manifest, indent=2))
    upgrade.verify_bundle(bundle)
    tar = output / "procollab-pilot.tar.gz"
    with tarfile.open(tar, "x:gz") as archive:
        archive.add(bundle, arcname="procollab-pilot")
    destination = output / ("procollab-pilot-management-" + revision[:7] + ".zip")
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.write(tar, arcname=tar.name)
    destination.chmod(0o600)
    return {
        "archive": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "backend_revision": upgrade.BASE["backend_revision"],
        "frontend_revision": upgrade.BASE["frontend_revision"],
        "tooling_revision": revision,
        "api_files": len(upgrade.PATCH_FILES),
        "changed_frontend_files": sum(
            upgrade.BASE["frontend_files"].get(name) != digest
            for name, digest in after.items()
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.api.resolve(), args.frontend.resolve(), args.output.resolve())
    import sys

    sys.stdout.write(json.dumps(result, indent=2) + "\n")

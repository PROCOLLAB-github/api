"""Пакет только измененной статики пилота поверх известной предыдущей сборки."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

import upgrade_frontend as upgrade


def package(frontend, base_manifest, output):
    upgrade.require(not output.exists(), "Каталог пакета уже существует.")
    base = json.loads(base_manifest.read_text())
    upgrade.require(
        base.get("api_revision") == upgrade.BACKEND, "Неизвестный исходный API."
    )
    before = {
        p.removeprefix("frontend/"): h
        for p, h in base["files"].items()
        if p.startswith("frontend/")
    }
    upgrade.require(
        before.get("index.html") == upgrade.BASE_INDEX, "Неизвестный исходный index."
    )
    after = {}
    for path in sorted(frontend.rglob("*")):
        upgrade.require(not path.is_symlink(), "Ссылка в сборке запрещена.")
        if path.is_file():
            after[str(path.relative_to(frontend))] = upgrade.hosted.digest(path)
    upgrade.hashes(before)
    upgrade.hashes(after)
    output.mkdir(mode=0o700, parents=True)
    bundle = output / "procollab-pilot"
    bundle.mkdir(mode=0o755)
    for relative in upgrade.HELPERS:
        shutil.copyfile(Path(__file__).parent / relative, bundle / relative)
    for relative, digest in after.items():
        if before.get(relative) != digest:
            target = bundle / "frontend" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(frontend / relative, target)
    manifest = {
        "format": upgrade.IDENTITY,
        "backend_revision": upgrade.BACKEND,
        "base_frontend_revision": upgrade.PREVIOUS,
        "frontend_revision": upgrade.REVISION,
        "base_files": before,
        "new_files": after,
        "files": {
            str(path.relative_to(bundle)): upgrade.hosted.digest(path)
            for path in sorted(bundle.rglob("*"))
            if path.is_file()
        },
    }
    (bundle / "frontend-manifest.json").write_text(json.dumps(manifest, indent=2))
    upgrade.verify_bundle(bundle)
    tar = output / "procollab-pilot.tar.gz"
    with tarfile.open(tar, "w:gz") as archive:
        archive.add(bundle, arcname="procollab-pilot")
    destination = output / ("procollab-pilot-auth-" + upgrade.REVISION[:7] + ".zip")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(tar, arcname=tar.name)
    return {
        "archive": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "frontend_revision": upgrade.REVISION,
        "backend_revision": upgrade.BACKEND,
        "changed_files": len(manifest["files"]) - len(upgrade.HELPERS),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(  # noqa: T201
        json.dumps(
            package(
                args.frontend.resolve(),
                args.base_manifest.resolve(),
                args.output.resolve(),
            ),
            indent=2,
        )
    )  # noqa: T201

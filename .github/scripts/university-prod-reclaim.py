"""Evict two exact obsolete caches only after authenticated registry verification."""
import json
import re
import shutil
import subprocess
from pathlib import Path

candidates = [
    (
        "sha256:e63af35f12a0f1459d85a8e76a8bceef935754176d6d9f61321b596dea639a24",
        "ghcr.io/procollab-github/api:prod-2026-04-23",
        "ghcr.io/procollab-github/api@sha256:510365cd95106933532ea44f958f7062833c2db1d06ad8f16c9aa543942e321b",
    ),
    (
        "sha256:891532409f2634b8642a5c7f9dd52220c48af305b4f2fbee519cb416f66d7c19",
        "ghcr.io/procollab-github/api:prod-295d85f",
        "ghcr.io/procollab-github/api@sha256:f1fc114ece6330e8a6ce6f2b1a18a5329339205480a53d7b92887b9e28bf0af0",
    ),
]


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def images():
    return set(docker("image", "ls", "-a", "--no-trunc", "--digests", "--format", "{{.ID}} {{.Repository}} {{.Tag}} {{.Digest}}").splitlines())


def containers():
    return {value: docker("inspect", "-f", "{{.Id}} {{.Image}} {{.State.Status}} {{.State.StartedAt}} {{.RestartCount}}", value) for value in docker("ps", "-aq", "--no-trunc").splitlines()}


candidate_ids = {image for image, tag, digest in candidates}
protected = {
    "sha256:e8b3ad5718a8efd7af843efbcf426d817c0d1824c0a699ebde4a366d37137577",
    "sha256:9b90cfcfeb9f6a418bbfedbc7a01d8af780e1c05dde885745c4239e9c3cd30e0",
}
base = Path("/var/backups/procollab-prod-analytics-cover")
assert base.is_dir() and not base.is_symlink()
for name in ("web.json", "celerys.json", "web-after.json", "celerys-after.json"):
    for path in base.glob("*/" + name):
        assert not path.is_symlink() and not path.parent.is_symlink()
        assert base.resolve() in path.resolve().parents and path.stat().st_size < 8192
        value = json.loads(path.read_text())["image_id"]
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", value)
        protected.add(value)
assert not candidate_ids & protected
before_containers = containers()
used = {docker("inspect", "-f", "{{.Image}}", value) for value in before_containers}
assert not candidate_ids & used
for image, tag, digest in candidates:
    assert docker("image", "inspect", "-f", "{{.Id}}", tag) == image
    assert json.loads(docker("image", "inspect", "-f", "{{json .RepoTags}}", image)) == [tag]
    assert digest in json.loads(docker("image", "inspect", "-f", "{{json .RepoDigests}}", image))
    assert not docker("ps", "-aq", "--filter", "ancestor=" + image)
    print("LOCAL_CACHE_MATCHES_VERIFIED_REGISTRY=" + digest, flush=True)
protected_images = {line for line in images() if line.split()[0] not in candidate_ids}
before_volumes = docker("volume", "ls", "--format", "{{.Driver}} {{.Name}}")
for image, tag, digest in candidates:
    assert not docker("ps", "-aq", "--filter", "ancestor=" + image)
    subprocess.run(["docker", "image", "rm", "--no-prune", tag], check=True)
assert images() == protected_images
assert containers() == before_containers
assert docker("volume", "ls", "--format", "{{.Driver}} {{.Name}}") == before_volumes
print("PROTECTED_IMAGES_UNCHANGED=true\nCONTAINERS_UNCHANGED=true\nVOLUMES_UNCHANGED=true", flush=True)
print("PROD_DISK_AVAILABLE_BYTES=" + str(shutil.disk_usage("/").free), flush=True)

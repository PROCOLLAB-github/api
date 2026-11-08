"""Remove only the four reviewed obsolete images, after explicit user approval."""

from datetime import datetime, timezone
import json
import re
import shutil
import subprocess

from prod_preflight import REPO, inspect_runtime, read

PLAN = "prod-obsolete-images-20261103-v1"
CANDIDATES = {
    "91ee8eff7532": "prod-celerys:latest",
    "79fd37732a6e": "ghcr.io/procollab-github/api:latest",
    "6a8d9cef0bf1": "grafana/grafana:latest",
    "24402908d513": "metabase/metabase:latest",
}
CUTOFF = datetime(2026, 5, 3, tzinfo=timezone.utc)


def used_images():
    containers = read(["docker", "ps", "--all", "--quiet"]).splitlines()
    if not containers:
        raise RuntimeError("Production container inventory is empty")
    return {
        read(["docker", "inspect", "--format", "{{.Image}}", container])
        for container in containers
    }


def validate_candidate(prefix, tag, info, used):
    identity = info["Id"]
    # Docker can report nanoseconds, which older host Python versions cannot parse.
    timestamp = re.sub(r"\.\d+(?=Z|[+-])", "", info["Created"])
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("Obsolete image creation time is invalid") from error
    if (
        prefix not in CANDIDATES
        or CANDIDATES[prefix] != tag
        or not identity.startswith("sha256:" + prefix)
        or info.get("RepoTags") != [tag]
        or identity in used
        or created >= CUTOFF
    ):
        raise RuntimeError("Obsolete image differs from the approved cleanup plan")
    return identity


def inspect_candidate(prefix):
    return json.loads(read(["docker", "image", "inspect", prefix]))[0]


def main(approved_plan):
    if approved_plan != PLAN:
        raise RuntimeError("Explicit approval of the fixed cleanup plan is required")
    before, services = inspect_runtime()
    used = used_images()
    # Validate the entire list before removing anything.
    candidates = [
        (prefix, tag, validate_candidate(prefix, tag, inspect_candidate(prefix), used))
        for prefix, tag in CANDIDATES.items()
    ]
    free_before = shutil.disk_usage(REPO).free
    for prefix, tag, identity in candidates:
        if (
            validate_candidate(prefix, tag, inspect_candidate(prefix), used_images())
            != identity
        ):
            raise RuntimeError("Obsolete image changed during cleanup")
        # No force: Docker also refuses removal if any container starts using it.
        result = subprocess.run(
            ["docker", "image", "rm", identity],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError("Guarded obsolete image removal stopped")
        print("PROD_APPROVED_OBSOLETE_IMAGE_REMOVED=" + prefix, flush=True)
    after, after_services = inspect_runtime()
    if services != after_services or before["source_sha"] != after["source_sha"]:
        raise RuntimeError("Production runtime changed during cleanup")
    print("PROD_OBSOLETE_IMAGE_CLEANUP_PLAN=" + PLAN, flush=True)
    print("PROD_OBSOLETE_IMAGE_COUNT=" + str(len(candidates)), flush=True)
    print(
        "PROD_DISK_BYTES_FREED=" + str(shutil.disk_usage(REPO).free - free_before),
        flush=True,
    )
    print("PROD_CLEANUP_SERVICES_UNCHANGED=true", flush=True)

"""Plan or remove old, reproducible DEV API images; never prune Docker globally."""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

TAG = re.compile(r"procollab-dev-api:([0-9a-f]{40})(?:-[0-9a-f]{12})?$")
REPO = "/root/api"


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def output(message):
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inventory():
    result = {}
    for image_id in set(command("docker", "image", "ls", "-aq", "--no-trunc").split()):
        value = json.loads(
            command(
                "docker",
                "image",
                "inspect",
                "--format",
                '{"id":{{json .Id}},"tags":{{json .RepoTags}},"created":{{json .Created}}}',
                image_id,
            )
        )
        value["tags"] = sorted(value["tags"] or [])
        result[image_id] = value
    return result


def containers():
    result = []
    for container_id in command("docker", "ps", "-aq", "--no-trunc").split():
        result.append(
            json.loads(
                command(
                    "docker",
                    "inspect",
                    "--format",
                    '{"id":{{json .Id}},"image":{{json .Image}},"state":{{json .State.Status}},'
                    '"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}}}',
                    container_id,
                )
            )
        )
    return sorted(result, key=lambda value: value["id"])


def volumes():
    return sorted(
        command(
            "docker", "volume", "ls", "--format", "{{.Driver}} {{.Name}}"
        ).splitlines()
    )


def created_at(image):
    value = re.sub(r"(\.\d{6})\d+", r"\1", image["created"])
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def plan(images, container_rows, volume_rows, now, reachable):
    used = {row["image"] for row in container_rows}
    reproducible = []
    for image in images.values():
        tags = image["tags"]
        matches = [TAG.fullmatch(tag) for tag in tags]
        if tags and all(matches) and all(reachable(match[1]) for match in matches):
            reproducible.append(image)
    newest = {
        image["id"]
        for image in sorted(
            reproducible, key=lambda row: (created_at(row), row["id"]), reverse=True
        )[:3]
    }
    candidates = sorted(
        (
            image
            for image in reproducible
            if image["id"] not in used | newest
            and created_at(image) < now - timedelta(hours=48)
        ),
        key=lambda image: image["id"],
    )
    proof = {
        "images": images,
        "containers": container_rows,
        "volumes": volume_rows,
        "candidates": candidates,
    }
    return {
        "sha256": digest(proof),
        "candidates": candidates,
        "protected_count": len(images) - len(candidates),
    }


def apply(plan_value, expected, images_before, containers_before, volumes_before):
    if plan_value["sha256"] != expected:
        raise RuntimeError("Image inventory changed; inspect a new plan before cleanup")
    remaining = dict(images_before)
    for image in plan_value["candidates"]:
        if (
            containers() != containers_before
            or volumes() != volumes_before
            or inventory() != remaining
        ):
            raise RuntimeError("Docker state changed; no further images will be removed")
        for tag in image["tags"]:
            # Non-force removal preserves images referenced by any container.
            # --no-prune also prevents removal of untagged parent images.
            subprocess.run(["docker", "image", "rm", "--no-prune", tag], check=True)
        del remaining[image["id"]]
    if (
        inventory() != remaining
        or containers() != containers_before
        or volumes() != volumes_before
    ):
        raise RuntimeError("Docker state differs from the reviewed removal plan")
    output(
        "PROTECTED_IMAGES_UNCHANGED=true\nCONTAINERS_UNCHANGED=true\nVOLUMES_UNCHANGED=true"
    )


def main():
    mode, expected = sys.argv[1:]
    require(mode in ("plan", "apply"), "Invalid operation")
    require(
        mode == "plan" or re.fullmatch(r"[0-9a-f]{64}", expected), "Inspect a plan first"
    )
    require(
        os.geteuid() == 0 and os.path.realpath(REPO) == REPO,
        "Unexpected host or repository",
    )
    command(
        "git",
        "-C",
        REPO,
        "merge-base",
        "--is-ancestor",
        "beef71645567128398d0afa5a2eb80dc6bc8dac7",
        "HEAD",
    )
    command(
        "grep",
        "-Eq",
        r"server_name[[:space:]]+dev\.procollab\.ru;",
        "/etc/nginx/sites-enabled/dev.procollab.ru",
    )
    runtime = []
    for service in ("web", "celerys"):
        container_id = command(
            "docker",
            "ps",
            "-q",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project.working_dir={REPO}",
            "--filter",
            f"label=com.docker.compose.service={service}",
        )
        require(
            re.fullmatch(r"[0-9a-f]{64}", container_id),
            "Expected one running DEV service",
        )
        reference = command("docker", "inspect", "-f", "{{.Config.Image}}", container_id)
        require(TAG.fullmatch(reference), "Unexpected DEV image reference")
        runtime.append(command("docker", "inspect", "-f", "{{.Image}}", container_id))
    require(len(set(runtime)) == 1, "DEV web and worker image mismatch")
    images_before, containers_before, volumes_before = (
        inventory(),
        containers(),
        volumes(),
    )

    def reachable(sha):
        return (
            subprocess.run(
                ["git", "-C", REPO, "merge-base", "--is-ancestor", sha, "HEAD"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )

    value = plan(
        images_before,
        containers_before,
        volumes_before,
        datetime.now(timezone.utc),
        reachable,
    )
    output("DEV_IMAGE_RETENTION_PLAN=" + json.dumps(value, sort_keys=True))
    output(command("df", "-h", "/"))
    if mode == "apply":
        apply(value, expected, images_before, containers_before, volumes_before)
        output(command("df", "-h", "/"))


if __name__ == "__main__":
    main()

"""Preserve unrelated server edits and prove they do not alter the released image."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

repo = Path("/home/app/procollab-backend")
backup = Path("/var/backups/procollab-prod-university-20261016")
phase, target = sys.argv[1:]
assert phase in ("before", "after") and re.fullmatch(r"[0-9a-f]{40}", target)
assert repo.resolve() == repo and backup.resolve() == backup
allowed = {
    "docs/notifications-api.md",
    "notifications/events.py",
    "notifications/migrations/0003_notification_image_url.py",
    "notifications/models.py",
    "notifications/serializers.py",
    "notifications/services.py",
    "notifications/tests/test_notification_images.py",
    "notifications/tests/test_notification_services.py",
    "notifications/tests/test_notifications_api.py",
    "notifications/tests/test_program_notification_events.py",
}


def git(*args):
    return subprocess.check_output(["sudo", "-n", "-u", "app", "git", "-C", str(repo), *args])


changed = set(filter(None, git("diff", "HEAD", "--name-only", "-z").decode().split("\0")))
assert changed <= allowed, changed - allowed
original = (backup / "backend-source-before.txt").read_text().strip()
release_files = set(filter(None, git("diff", original, target, "--name-only", "-z").decode().split("\0")))
assert not release_files & changed, release_files & changed
patch = git("diff", "HEAD", "--binary", "--full-index", "--no-ext-diff")
receipt = backup / "server-notification-edits-before.patch"
digest = hashlib.sha256(patch).hexdigest()
if phase == "before":
    assert git("rev-parse", "HEAD").decode().strip() == original
    if receipt.exists():
        assert receipt.read_bytes() == patch, "Server edits changed after preservation"
    else:
        receipt.write_bytes(patch)
        receipt.chmod(0o600)
    container = subprocess.check_output([
        "docker", "ps", "-q", "--no-trunc",
        "--filter", "label=com.docker.compose.project=prod",
        "--filter", "label=com.docker.compose.service=web",
    ], text=True).strip()
    assert re.fullmatch(r"[0-9a-f]{64}", container)
    mounts = json.loads(subprocess.check_output(["docker", "inspect", "-f", "{{json .Mounts}}", container], text=True))
    assert all(mount["Destination"] == "/procollab/log" for mount in mounts), mounts
    for name in sorted(changed):
        expected = git("show", original + ":" + name).replace(b"\r\n", b"\n")
        actual = subprocess.check_output(["docker", "exec", container, "cat", "/procollab/" + name]).replace(b"\r\n", b"\n")
        assert actual == expected, "Running image differs from original source: " + name
        assert git("show", target + ":" + name).replace(b"\r\n", b"\n") == expected
    print("RUNNING_NOTIFICATION_CODE_MATCHES_RELEASE=true")
    print("SERVER_EDITS_BACKUP_SHA256=" + digest)
else:
    assert git("rev-parse", "HEAD").decode().strip() == target
    assert receipt.read_bytes() == patch, "Unrelated server edits changed during checkout"
    print("UNRELATED_SERVER_EDITS_PRESERVED=true")
print("UNRELATED_SERVER_EDIT_FILE_COUNT=" + str(len(changed)))

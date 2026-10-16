#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
repo=/home/app/procollab-backend
snapshot=/var/backups/procollab-prod-university-20261016
web=$1
ops_sha=$2
run_id=$3
attempt=$4
[[ "$web" =~ ^[0-9a-f]{64}$ ]]
[[ "$ops_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$run_id" =~ ^[0-9]+$ && "$attempt" =~ ^[0-9]+$ ]]
test "$(id -u)" = 0
test -f "$snapshot/COMPLETE"
test "$(docker inspect -f '{{.Image}}' "$web")" = "$(cat "$snapshot/backend-image-id-before.txt")"
baseline="$snapshot/education-before-deploy-$run_id-$attempt.json"
test ! -e "$baseline"
sudo -n -u app git -C "$repo" show "$ops_sha:.github/scripts/university-prod-check.py" |
  docker exec -i "$web" python - snapshot > "$baseline"
chmod 600 "$baseline"
python3 - "$baseline" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
canonical = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
print('EDUCATION_DEPLOY_BASELINE_COUNT=' + str(len(payload['rows'])))
print('EDUCATION_DEPLOY_BASELINE_SHA256=' + hashlib.sha256(canonical).hexdigest())
PY
printf '%s\n' "$baseline" > "$snapshot/education-checkpoint.txt"
printf 'PROD_IMMEDIATE_EDUCATION_CHECKPOINT_COMPLETE=true\n'

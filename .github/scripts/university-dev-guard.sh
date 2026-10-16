#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

phase=$1
expected_sha=$2
ops_sha=$3
repo=/root/api
snapshot=/root/procollab-dev-university-20261016
test "$(readlink -f "$repo")" = "$repo"
test "$(id -u)" -eq 0
[[ "$ops_sha" =~ ^[0-9a-f]{40}$ ]]
case "$phase" in snapshot|verify) ;; *) exit 1 ;; esac
grep -Eq 'server_name[[:space:]]+dev\.procollab\.ru;' /etc/nginx/sites-enabled/dev.procollab.ru
cd "$repo"
source_sha=$(git --no-optional-locks rev-parse HEAD)
printf 'DEV_SOURCE_SHA=%s\n' "$source_sha"

if [ "$phase" = snapshot ]; then
  test "$source_sha" = 81bd6fecc97e8f4355f8ca26f15aa780cf607fe4
else
  [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]]
  test "$source_sha" = "$expected_sha"
  test -f "$snapshot/COMPLETE"
fi

expected_image_id=$(docker image inspect -f '{{.Id}}' "procollab-dev-api:${source_sha}")
for service in web celerys; do
  container=$(docker ps -q --no-trunc --filter "label=com.docker.compose.project.working_dir=$repo" --filter "label=com.docker.compose.service=$service")
  [[ "$container" =~ ^[0-9a-f]{64}$ ]]
  test "$(docker inspect -f '{{.Image}}' "$container")" = "$expected_image_id"
  printf 'DEV_SERVICE=%s\n' "$service"
  docker inspect -f '{"image_reference":{{json .Config.Image}},"image_id":{{json .Image}},"status":{{json .State.Status}}}' "$container"
  if [ "$service" = web ]; then
    export DEPLOY_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$container")
  fi
done
printf 'DEV_RUNTIME_MATCHES_SOURCE=true\n'

if [ "$phase" = snapshot ]; then
  test ! -e "$snapshot"
  df -Pk /
  available_kb=$(df -Pk / | awk 'NR==2 {print $4}')
  test "$available_kb" -ge 3145728
  install -d -m 700 "$snapshot"
  printf '%s\n' "$source_sha" > "$snapshot/backend-source-before.txt"
  printf '%s\n' "$DEPLOY_IMAGE" > "$snapshot/backend-image-before.txt"
  cp --preserve=mode .env "$snapshot/backend.env.before"
  test -f /home/front/app/index.html
  tar -czf "$snapshot/frontend-before.tar.gz" -C /home/front app
  gzip -t "$snapshot/frontend-before.tar.gz"
  sha256sum /home/front/app/index.html > "$snapshot/frontend-index-before.sha256"
  git show "$ops_sha:.github/scripts/university-dev-check.py" |
    docker compose -f docker-compose.dev-ci.yml run --rm -T --no-deps web python - snapshot > "$snapshot/education-before.json"
  python3 - "$snapshot/education-before.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
canonical = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
print('EDUCATION_BASELINE_COUNT=' + str(len(payload['rows'])))
print('EDUCATION_BASELINE_SHA256=' + hashlib.sha256(canonical).hexdigest())
PY
  chmod 600 "$snapshot"/*
  touch "$snapshot/COMPLETE"
  printf 'DEV_PRIVATE_BACKUP_COMPLETE=true\n'
else
  git show "$ops_sha:.github/scripts/university-dev-check.py" |
    docker compose -f docker-compose.dev-ci.yml run --rm -T --no-deps -v "$snapshot:/university_rollout:ro" web python - verify
  for path in /admin/login/ /auth/universities/; do
    status=$(curl --fail --silent --show-error -o /dev/null -w '%{http_code}' "https://dev.procollab.ru${path}")
    test "$status" = 200
    printf 'DEV_HTTP_%s=%s\n' "$path" "$status"
  done
  nginx -t
  printf 'DEV_EDUCATION_VERIFICATION_COMPLETE=true\n'
fi

#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
phase=$1
expected_sha=$2
ops_sha=$3
repo=/home/app/procollab-backend
snapshot=/var/backups/procollab-prod-university-20261016
test "$(id -u)" = 0
test "$(readlink -f "$repo")" = "$repo"
[[ "$ops_sha" =~ ^[0-9a-f]{40}$ ]]
case "$phase" in inspect|snapshot|verify) ;; *) exit 1 ;; esac
source_sha=$(sudo -n -u app git --no-optional-locks -C "$repo" rev-parse HEAD)
if [ "$phase" != verify ]; then
  test "$source_sha" = 5ee91f873a9fb2d232963dc37b3905224e5665cc
else
  [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]]
  test "$source_sha" = "$expected_sha"
  test -f "$snapshot/COMPLETE"
fi
printf 'PROD_SOURCE_SHA=%s\n' "$source_sha"
for service in web celerys; do
  container=$(docker ps -q --no-trunc --filter label=com.docker.compose.project=prod --filter "label=com.docker.compose.service=$service")
  [[ "$container" =~ ^[0-9a-f]{64}$ ]]
  test "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container")" = "$repo"
  test "$(docker inspect -f '{{.State.Status}}' "$container")" = running
  image_id=$(docker inspect -f '{{.Image}}' "$container")
  test "$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")" = "$source_sha"
  printf 'PROD_SERVICE=%s\n' "$service"
  docker inspect -f '{"image_reference":{{json .Config.Image}},"image_id":{{json .Image}},"status":{{json .State.Status}},"restart_count":{{.RestartCount}}}' "$container"
  if [ "$service" = web ]; then web=$container; image_ref=$(docker inspect -f '{{.Config.Image}}' "$web"); fi
done
df -h / /var/lib/docker
df -i /
available=$(df -PB1 / | awk 'NR==2 {print $4}')
printf 'PROD_DISK_AVAILABLE_BYTES=%s\n' "$available"
docker image inspect -f 'PROD_CURRENT_IMAGE_BYTES={{.Size}}' "$image_id"
if [ "$phase" = inspect ]; then
  printf 'HOST_PG_DUMP='; command -v pg_dump || true
  docker exec "$web" sh -c 'command -v pg_dump || true'
  docker exec "$web" python -c 'import os; os.environ.setdefault("DJANGO_SETTINGS_MODULE","procollab.settings"); import django; django.setup(); from django.db import connection; c=connection.cursor(); c.execute("SET default_transaction_read_only = on"); c.execute("SHOW server_version"); print("PROD_DB_VERSION="+c.fetchone()[0]); c.execute("SELECT pg_database_size(current_database())"); print("PROD_DATABASE_BYTES="+str(c.fetchone()[0]))'
  docker system df
  printf 'PROD_INSPECTION_COMPLETE=true\n'
  exit 0
fi
if [ "$phase" = snapshot ]; then
  test ! -e "$snapshot"
  test "$available" -gt 1073741824
  install -d -m 700 "$snapshot"
  printf '%s\n' "$source_sha" > "$snapshot/backend-source-before.txt"
  printf '%s\n' "$image_ref" > "$snapshot/backend-image-before.txt"
  printf '%s\n' "$image_id" > "$snapshot/backend-image-id-before.txt"
  cp -p "$repo/.env" "$snapshot/backend.env.before"
  cp -p "$repo/docker-compose.prod-ci.yml" "$snapshot/docker-compose.prod-ci.yml"
  sudo -n -u app git -C "$repo" show "$ops_sha:.github/scripts/university-prod-check.py" |
    docker exec -i "$web" python - snapshot > "$snapshot/education-before.json"
  python3 - "$snapshot/education-before.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
print('EDUCATION_BASELINE_COUNT=' + str(len(payload['rows'])))
print('EDUCATION_BASELINE_SHA256=' + hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest())
PY
  chmod 600 "$snapshot"/*
  touch "$snapshot/COMPLETE"
  printf 'PROD_PRIVATE_EDUCATION_BACKUP_COMPLETE=true\n'
else
  docker cp "$snapshot/education-before.json" "$web:/tmp/university-education-before-20261016.json"
  docker exec "$web" chmod 600 /tmp/university-education-before-20261016.json
  sudo -n -u app git -C "$repo" show "$ops_sha:.github/scripts/university-prod-check.py" |
    docker exec -i "$web" python - verify
  for path in /admin/login/ /auth/universities/; do
    status=$(curl --fail --silent --show-error -o /dev/null -w '%{http_code}' "https://api.procollab.ru${path}")
    test "$status" = 200
    printf 'PROD_HTTP_%s=%s\n' "$path" "$status"
  done
  nginx -t
  printf 'PROD_EDUCATION_VERIFICATION_COMPLETE=true\n'
fi

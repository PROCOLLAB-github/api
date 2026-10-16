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
case "$phase" in inspect|reclaim|snapshot|plan|verify) ;; *) exit 1 ;; esac
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
  printf 'PROD_IMAGE_INVENTORY\n'
  docker image ls -a --no-trunc --digests --format '{{.ID}} {{.Repository}}:{{.Tag}} {{.Digest}} {{.Size}}'
  printf 'PROD_CONTAINER_IMAGE_REFERENCES\n'
  for id in $(docker ps -aq --no-trunc); do
    docker inspect -f '{{.Image}} {{.Config.Image}}' "$id"
  done
  printf 'PG_CLIENT_LOCATIONS\n'
  for base in /usr/lib/postgresql/14/bin /usr/lib/postgresql/15/bin /usr/bin /bin; do
    for client in pg_dump pg_restore psql; do
      if test -x "$base/$client"; then printf '%s\n' "$base/$client"; fi
    done
  done
  printf 'PROD_INSPECTION_COMPLETE=true\n'
  exit 0
fi
if [ "$phase" = reclaim ]; then
  test "${4:-}" = true
  sudo -n -u app git -C "$repo" show "$ops_sha:.github/scripts/university-prod-reclaim.py" | python3 -
  exit 0
fi
if [ "$phase" = plan ]; then
  [[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]]
  test -f "$snapshot/COMPLETE"
  sudo -n -u app git -C "$repo" fetch origin release/prod-university-directory
  test "$(sudo -n -u app git -C "$repo" rev-parse origin/release/prod-university-directory)" = "$expected_sha"
  candidate="$snapshot/candidate-$expected_sha-${ops_sha:0:12}"
  test ! -e "$candidate"
  install -d -m 700 "$candidate"
  sudo -n -u app git -C "$repo" archive "$expected_sha" | tar -x -C "$candidate"
  install -d -m 700 "$candidate/log"
  sudo -n -u app git -C "$repo" show "$ops_sha:.github/scripts/university-prod-plan.py" |
    docker run --rm -i --network "container:$web" --env-file "$repo/.env" --mount "type=bind,src=$candidate,dst=/procollab,readonly" --mount type=tmpfs,destination=/procollab/log --entrypoint python "$image_id" -
  printf 'PROD_READONLY_CANDIDATE_MIGRATION_PLAN_COMPLETE=true\n'
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
  client=postgres:14-alpine
  had_client=false
  if docker image inspect "$client" >/dev/null 2>&1; then had_client=true; fi
  docker pull "$client"
  client_id=$(docker image inspect -f '{{.Id}}' "$client")
  docker exec -i "$web" python - <<'PY' > "$snapshot/pg-backup.env"
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')
import django
django.setup()
from django.conf import settings
db = settings.DATABASES['default']
values = {'PGHOST': db['HOST'], 'PGPORT': str(db['PORT'] or 5432), 'PGDATABASE': db['NAME'], 'PGUSER': db['USER'], 'PGPASSWORD': db['PASSWORD'], 'PGSSLMODE': db.get('OPTIONS', {}).get('sslmode', 'prefer')}
assert all('\n' not in value and '\r' not in value for value in values.values())
for key, value in values.items():
    print(key + '=' + value)
PY
  docker run --rm --network "container:$web" --env-file "$snapshot/pg-backup.env" --entrypoint pg_dump "$client_id" --format=custom --no-owner --no-acl > "$snapshot/database-before.dump"
  test -s "$snapshot/database-before.dump"
  docker run --rm -i --entrypoint pg_restore "$client_id" --list < "$snapshot/database-before.dump" > "$snapshot/database-before.toc"
  docker run --rm -i --entrypoint pg_restore "$client_id" --file=/dev/null < "$snapshot/database-before.dump"
  python3 - "$snapshot/pg-backup.env" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).unlink()
PY
  sha256sum "$snapshot/database-before.dump"
  printf 'PROD_DATABASE_BACKUP_VALIDATED=true\n'
  if [ "$had_client" = false ]; then
    test -z "$(docker ps -aq --filter "ancestor=$client_id")"
    test "$(docker image inspect -f '{{.Id}}' "$client")" = "$client_id"
    docker image rm --no-prune "$client"
  fi
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

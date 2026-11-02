"""DEV-only read-only data checks and a protected, validated database backup."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

REPO = Path('/root/api')
BACKUPS = Path('/root/procollab-dependency-backups')
KEY = re.compile(r'dependency-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}')

PROBE = r'''
import hashlib, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'procollab.settings')
import django
django.setup()
from django.db import connection, transaction
payload = {'django': django.get_version(), 'tables': {}}
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("SELECT current_database(), current_setting('server_version_num')::int, pg_database_size(current_database())")
        name, version, size = cursor.fetchone()
        if name != 'procollab_db_dev' or not 140000 <= version < 190000:
            raise RuntimeError('Unexpected DEV database or unsupported PostgreSQL version')
        payload.update(server_major=version // 10000, database_bytes=size)
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        tables = [row[0] for row in cursor.fetchall() if row[0].startswith(('users_', 'projects_', 'partner_programs_', 'project_rates_', 'files_'))]
        for table in tables:
            cursor.execute('SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid=to_regclass(%s) AND i.indisprimary ORDER BY a.attnum', [table])
            primary = [row[0] for row in cursor.fetchall()]
            if not primary:
                raise RuntimeError('Missing primary key in a protected table')
            identity = 'jsonb_build_array(' + ','.join('t.' + connection.ops.quote_name(key) for key in primary) + ')::text'
            record = "(to_jsonb(t) - 'last_activity' - 'last_login' - 'datetime_updated')::text"
            hash_sql = lambda expression: "encode(sha256(convert_to(" + expression + ", 'UTF8')), 'hex')"
            cursor.execute('SELECT ' + hash_sql(identity) + ',' + hash_sql(record) + ' FROM ' + connection.ops.quote_name(table) + ' t')
            records = {}
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    break
                for identity, record_hash in batch:
                    records[identity] = record_hash
            payload['tables'][table] = records
print(json.dumps(payload, ensure_ascii=False))
'''


def command(args, **kwargs):
    try:
        return subprocess.run(args, check=True, stderr=subprocess.PIPE, **kwargs)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError('A DEV backup/check command failed; no credentials are printed') from None


def output(args, **kwargs):
    return command(args, stdout=subprocess.PIPE, **kwargs).stdout


def inspect_container(container):
    value = json.loads(output(['docker', 'inspect', container]))[0]
    labels = value['Config'].get('Labels', {})
    paths = labels.get('com.docker.compose.project.config_files', '').split(',')
    if str(REPO / 'docker-compose.dev-ci.yml') not in paths:
        raise RuntimeError('Container does not belong to the DEV compose configuration')
    return value


def snapshot(web):
    return json.loads(output(['docker', 'exec', '-i', web, 'python', '-'], input=PROBE.encode(), timeout=180))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    phase = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else ''
    if phase not in ('backup', 'verify') or REPO.resolve() != REPO:
        raise RuntimeError('Invalid operation or repository location')
    os.umask(0o077)
    os.chdir(REPO)
    web = output(['docker', 'compose', '-f', 'docker-compose.dev-ci.yml', 'ps', '-q', 'web'], text=True).strip()
    worker = output(['docker', 'compose', '-f', 'docker-compose.dev-ci.yml', 'ps', '-q', 'celerys'], text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{12,64}', web) or not re.fullmatch(r'[a-f0-9]{12,64}', worker):
        raise RuntimeError('Expected exactly one running DEV web and worker')
    runtime = inspect_container(web)
    worker_runtime = inspect_container(worker)
    if runtime['Image'] != worker_runtime['Image']:
        raise RuntimeError('DEV web and worker use different images')
    current = snapshot(web)
    print('POSTGRESQL_MAJOR=' + str(current['server_major']), flush=True)
    print('DJANGO_RUNTIME=' + current['django'], flush=True)

    if phase == 'backup':
        required = max(2 * 1024**3, current['database_bytes'] * 2 + 512 * 1024**2)
        if shutil.disk_usage('/root').free < required:
            raise RuntimeError('Insufficient free space for a protected DEV backup and rollout')
        key = 'dependency-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
        BACKUPS.mkdir(mode=0o700, exist_ok=True)
        folder = BACKUPS / key
        folder.mkdir(mode=0o700)
        dump = folder / 'database.dump'
        environment_script = 'import json,os; print(json.dumps({k:os.environ[k] for k in ("DATABASE_HOST","DATABASE_PORT","DATABASE_NAME","DATABASE_USER","DATABASE_PASSWORD")}))'
        config = json.loads(output(['docker', 'exec', web, 'python', '-c', environment_script]))
        if config['DATABASE_NAME'] != 'procollab_db_dev':
            raise RuntimeError('Unexpected DEV database configuration')
        environment = dict(os.environ)
        for destination, source in (('PGHOST', 'DATABASE_HOST'), ('PGPORT', 'DATABASE_PORT'), ('PGDATABASE', 'DATABASE_NAME'), ('PGUSER', 'DATABASE_USER'), ('PGPASSWORD', 'DATABASE_PASSWORD')):
            environment[destination] = config[source]
        client = 'postgres:' + str(current['server_major']) + '-alpine'
        container_name = 'dependency-backup-' + uuid4().hex[:12]
        try:
            with dump.open('xb') as handle:
                command(['docker', 'run', '--rm', '--name', container_name, '--network', 'container:' + web,
                         '--env', 'PGHOST', '--env', 'PGPORT', '--env', 'PGDATABASE', '--env', 'PGUSER', '--env', 'PGPASSWORD',
                         client, 'pg_dump', '--format=custom', '--no-owner', '--no-acl', '--lock-wait-timeout=30s'],
                        env=environment, stdout=handle, timeout=600)
        finally:
            subprocess.run(['docker', 'rm', '-f', container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with dump.open('rb') as handle:
            if handle.read(5) != b'PGDMP':
                raise RuntimeError('Invalid backup archive')
            handle.seek(0)
            command(['docker', 'run', '--rm', '-i', client, 'pg_restore', '--file=/dev/null'],
                    stdin=handle, stdout=subprocess.DEVNULL, timeout=600)
        rollback = 'procollab-dependency-rollback:' + key
        command(['docker', 'tag', runtime['Image'], rollback], stdout=subprocess.DEVNULL)
        shutil.copyfile(REPO / '.env', folder / 'runtime.env')
        os.chmod(folder / 'runtime.env', 0o600)
        metadata = {'snapshot': current, 'image_id': runtime['Image'], 'image': runtime['Config']['Image'],
                    'rollback_tag': rollback, 'source_sha': output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                    'dump_sha256': digest(dump), 'dump_bytes': dump.stat().st_size}
        (folder / 'manifest.json').write_text(json.dumps(metadata), encoding='utf8')
        print('BACKUP_KEY=' + key)
        print('BACKUP_BYTES=' + str(metadata['dump_bytes']))
        print('BACKUP_SHA256=' + metadata['dump_sha256'])
        print('ROLLBACK_IMAGE=' + rollback)
    else:
        if KEY.fullmatch(key) is None:
            raise RuntimeError('Invalid backup key')
        folder = BACKUPS / key
        if folder.resolve().parent != BACKUPS.resolve():
            raise RuntimeError('Invalid backup location')
        before = json.loads((folder / 'manifest.json').read_text(encoding='utf8'))
        if digest(folder / 'database.dump') != before['dump_sha256']:
            raise RuntimeError('Backup digest mismatch')
        removed, changed = {}, {}
        for table, records in before['snapshot']['tables'].items():
            after = current['tables'].get(table, {})
            missing = set(records) - set(after)
            different = [identity for identity in set(records) & set(after) if records[identity] != after[identity]]
            if missing:
                removed[table] = len(missing)
            if different:
                changed[table] = len(different)
        print('REMOVED_EXISTING_RECORDS=' + json.dumps(removed))
        print('CHANGED_EXISTING_RECORDS=' + json.dumps(changed))
        if removed or changed:
            raise RuntimeError('Existing DEV records changed; inspect before continuing')
        print('EXISTING_DEV_DATA_PRESERVED=true')
        print('CURRENT_IMAGE=' + runtime['Config']['Image'])
    print('PROTECTED_TABLE_COUNTS=' + json.dumps({name: len(rows) for name, rows in current['tables'].items()}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('DEV_DEPENDENCY_PREFLIGHT_FAILED=' + type(error).__name__, file=sys.stderr)
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        raise SystemExit(1)

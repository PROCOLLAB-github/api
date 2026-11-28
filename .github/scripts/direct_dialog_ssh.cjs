const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { deploy } = require('../../scripts/dev_ci_ssh.cjs');

async function run() {
  const action = process.argv[2];
  const sha = process.env.GITHUB_SHA;
  if (!['prepare', 'cleanup', 'recover', 'prepare-storage'].includes(action) || !/^[a-f0-9]{40}$/.test(sha)) {
    throw new Error('Invalid direct dialog acceptance arguments');
  }
  const runAttempt = action === 'recover' ? process.env.DIRECT_DIALOG_RECOVERY_RUN
    : `${process.env.GITHUB_RUN_ID}:${process.env.GITHUB_RUN_ATTEMPT}`;
  if (!/^[0-9]+:[0-9]+$/.test(runAttempt)) throw new Error('Invalid fixture run ID or attempt');
  const key = createHash('sha256')
    .update(runAttempt)
    .digest('hex')
    .slice(0, 24);
  const fixturePath = path.join(process.env.RUNNER_TEMP, 'direct-dialog.json');
  const receiptPaths = ['browser-selected', 'api-selected'].map((type) => `${fixturePath}.${type}`);
  const selectedIds = action === 'cleanup'
    ? receiptPaths.filter((file) => fs.existsSync(file)).map((file) => fs.readFileSync(file, 'utf8'))
    : [];
  if (!selectedIds.every((id) => /^[1-9][0-9]{0,15}$/.test(id))) throw new Error('Invalid reported message ID');

  let stdout = '';
  let stderr = '';
  const source = fs.readFileSync(path.join(__dirname, 'direct_dialog_fixture.py'), 'utf8').replace(/\r\n/g, '\n');
  const script = [
    'set +x',
    'set -eu',
    'cd /root/api',
    ...(action === 'prepare' ? [`test "$(git rev-parse HEAD)" = "${sha}"`] : []),
    'web="$(docker compose -f docker-compose.dev-ci.yml ps -q web)"',
    'test -n "$web"',
    ...(action === 'prepare' ? [
      `case "$(docker inspect -f '{{.Config.Image}}' "$web")" in procollab-dev-api:${sha}-*) ;; *) exit 31 ;; esac`,
      'docker exec "$web" python manage.py migrate --check >&2',
    ] : []),
    `docker exec -e DIRECT_DIALOG_QA_KEY=${key} -e DIRECT_DIALOG_QA_ACTION=${action === 'recover' ? 'cleanup' : action} -e DIRECT_DIALOG_QA_SELECTED=${selectedIds.join(',')} -i "$web" python - <<'DIRECT_DIALOG_FIXTURE'`,
    source,
    'DIRECT_DIALOG_FIXTURE',
  ].join('\n');
  try {
    await deploy({
      host: process.env.DEV_SERVER_HOST,
      username: process.env.DEV_SERVER_USER,
      password: process.env.DEV_SERVER_PASSWORD,
      hostFingerprint: process.env.DEV_SSH_HOST_KEY_SHA256,
      script,
      timeoutMs: 120000,
    }, { write: (chunk) => { stdout += chunk; } }, { write: (chunk) => { stderr += chunk; } });
    if (action === 'prepare') {
      const fixture = JSON.parse(stdout.trim().split('\n').at(-1));
      if (fixture.origin !== 'https://dev.procollab.ru' || fixture.accounts.length !== 2) {
        throw new Error('Invalid fixture');
      }
      fs.writeFileSync(fixturePath, JSON.stringify(fixture), { mode: 0o600 });
      console.log(`Prepared two synthetic dev accounts on ${sha}`);
    } else if (action === 'prepare-storage') {
      const { create_status, head_status, private: isPrivate } = JSON.parse(stdout.trim().split('\n').at(-1));
      console.log(`Dedicated DEV container: create=${create_status}, head=${head_status}, private=${isPrivate}`);
      if (!isPrivate) throw new Error('Private storage missing');
    } else if (stdout.trim()) {
      const receipt = JSON.parse(stdout.trim().split('\n').at(-1));
      console.log(`Removed ${receipt.cleaned} synthetic accounts; selected reports saved: ${receipt.selected_reports_saved}`);
      if (receipt.storage_failures?.length) {
        console.log(`Deactivated ${receipt.deactivated} synthetic accounts; storage cleanup: ${receipt.storage_failures}`);
        throw new Error('Storage cleanup incomplete');
      }
      if (receipt.selected_reports_saved !== selectedIds.length) throw new Error('Expected report missing');
    } else if (selectedIds.length) {
      throw new Error('Expected fixture missing');
    }
  } catch (error) {
    const exception = /^([\w.]*?(?:Error|Exception|Violation|Denied)):/m.exec(stderr)?.[1];
    if (exception) console.error(`DEV fixture exception: ${exception}`);
    throw error;
  } finally {
    if (action === 'cleanup') {
      fs.rmSync(fixturePath, { force: true });
      for (const receiptPath of receiptPaths) fs.rmSync(receiptPath, { force: true });
    }
  }
}

run().catch(() => {
  console.error('DEV direct dialog fixture failed.');
  process.exitCode = 1;
});

const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { deploy } = require('../../scripts/dev_ci_ssh.cjs');

async function run() {
  const action = process.argv[2];
  const sha = process.env.GITHUB_SHA;
  if (!['prepare', 'cleanup'].includes(action) || !/^[a-f0-9]{40}$/.test(sha)) {
    throw new Error('Invalid direct dialog acceptance arguments');
  }
  const key = createHash('sha256')
    .update(`${process.env.GITHUB_RUN_ID}:${process.env.GITHUB_RUN_ATTEMPT}`)
    .digest('hex')
    .slice(0, 24);
  const fixturePath = path.join(process.env.RUNNER_TEMP, 'direct-dialog.json');
  const receiptPath = `${fixturePath}.selected`;
  const selected = action === 'cleanup' && fs.existsSync(receiptPath) ? fs.readFileSync(receiptPath, 'utf8') : '0';
  if (!/^[0-9]{1,16}$/.test(selected)) throw new Error('Invalid reported message ID');

  let stdout = '';
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
    `docker exec -e DIRECT_DIALOG_QA_KEY=${key} -e DIRECT_DIALOG_QA_ACTION=${action} -e DIRECT_DIALOG_QA_SELECTED=${selected} -i "$web" python - <<'DIRECT_DIALOG_FIXTURE'`,
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
    }, { write: (chunk) => { stdout += chunk; } }, { write: () => {} });
    if (action === 'prepare') {
      const fixture = JSON.parse(stdout.trim().split('\n').at(-1));
      if (fixture.origin !== 'https://dev.procollab.ru' || fixture.accounts.length !== 2) {
        throw new Error('Invalid fixture');
      }
      fs.writeFileSync(fixturePath, JSON.stringify(fixture), { mode: 0o600 });
      console.log(`Prepared two synthetic dev accounts on ${sha}`);
    } else if (stdout.trim()) {
      const receipt = JSON.parse(stdout.trim().split('\n').at(-1));
      console.log(`Removed ${receipt.cleaned} synthetic accounts; selected report saved: ${receipt.selected_report_saved}`);
      if (selected !== '0' && !receipt.selected_report_saved) throw new Error('Expected report missing');
    }
  } finally {
    if (action === 'cleanup') {
      fs.rmSync(fixturePath, { force: true });
      fs.rmSync(receiptPath, { force: true });
    }
  }
}

run().catch(() => {
  console.error('DEV direct dialog fixture failed.');
  process.exitCode = 1;
});

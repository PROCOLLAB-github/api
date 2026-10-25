const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const yaml = fs.readFileSync('.github/workflows/dev-image-retention.yml', 'utf8').replace(/\r/g, '');
const source = yaml.split("          node <<'NODE'\n")[1].split('\n          NODE')[0].replace(/^          /gm, '');

async function execute(mode, digest, fail = false) {
  const calls = [];
  const errors = [];
  const context = {
    process: { env: {
      RETENTION_MODE: mode,
      PLAN_SHA256: digest,
      DEV_SERVER_HOST: 'dev-host',
      DEV_SERVER_USER: 'dev-user',
      DEV_SERVER_PASSWORD: 'synthetic-secret',
      DEV_SSH_HOST_KEY_SHA256: 'pinned-dev-key',
    }, exitCode: 0 },
    console: { error: message => errors.push(message) },
    require(name) {
      if (name === 'node:fs') return { readFileSync: () => 'print("PLAN")' };
      assert.equal(name, './scripts/dev_ci_ssh.cjs');
      return { deploy: async config => {
        calls.push(config);
        if (fail) throw new Error('DEV SSH deployment failed');
      } };
    },
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return { calls, errors, context };
}

test('plan actually invokes the exported SSH transport with separate credentials', async () => {
  const { calls, context } = await execute('plan', '');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].hostFingerprint, 'pinned-dev-key');
  assert.equal(calls[0].password, 'synthetic-secret');
  assert.match(calls[0].script, /python3 - plan none <<'DEV_IMAGE_RETENTION_PY'/);
  assert.ok(!calls[0].script.includes('synthetic-secret'));
  assert.equal(context.process.exitCode, 0);
});

test('apply passes exactly the reviewed hexadecimal inventory digest', async () => {
  const { calls } = await execute('apply', 'a'.repeat(64));
  assert.equal(calls.length, 1);
  assert.ok(calls[0].script.includes('python3 - apply ' + 'a'.repeat(64)));
});

test('invalid modes and shell text are rejected before the transport', async () => {
  await assert.rejects(execute('other', ''), /Invalid mode/);
  await assert.rejects(execute('plan', '$(id)'), /Invalid plan digest/);
  await assert.rejects(execute('apply', ''), /Inspect a plan first/);
});

test('remote failure makes the workflow fail instead of reporting a successful plan', async () => {
  const { calls, errors, context } = await execute('plan', '', true);
  assert.equal(calls.length, 1);
  assert.equal(context.process.exitCode, 1);
  assert.deepEqual(errors, ['DEV SSH deployment failed']);
});

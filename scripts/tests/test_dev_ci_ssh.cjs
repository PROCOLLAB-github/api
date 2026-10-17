const assert = require('node:assert/strict');
const { once } = require('node:events');
const { PassThrough } = require('node:stream');
const { spawn } = require('node:child_process');
const { test } = require('node:test');
const { Server, utils } = require('ssh2');
const { deploy, fingerprint } = require('../dev_ci_ssh.cjs');

// Ephemeral keys and credentials exist only in memory, for a loopback SSH server.
const keys = utils.generateKeyPairSync('ed25519');
const hostFingerprint = fingerprint(utils.parseKey(keys.private).getPublicSSH());
const password = 'fixture-only-password';
const script = 'set +x\nset -eu\ncat <<\'PAYLOAD\'\nfixture $() `secret`\nPAYLOAD\n';

async function fixture(context, options = {}) {
  const observed = { commands: [], input: '', authenticated: false };
  const connections = new Set();
  const server = new Server({ hostKeys: [keys.private] }, (connection) => {
    connections.add(connection);
    connection.on('error', () => {});
    connection.on('close', () => connections.delete(connection));
    connection.on('authentication', (auth) => {
      observed.authenticated = true;
      if (auth.method === 'password' && auth.username === 'fixture' && auth.password === password) {
        auth.accept();
      } else auth.reject();
    });
    connection.on('ready', () => connection.on('session', (accept) => {
      const session = accept();
      session.on('exec', (acceptCommand, rejectCommand, info) => {
        observed.commands.push(info.command);
        const stream = acceptCommand();
        stream.on('data', (chunk) => { observed.input += chunk.toString(); });
        if (options.bash) {
          const child = spawn(options.bash, ['-se'], { stdio: ['pipe', 'pipe', 'pipe'] });
          child.stdout.pipe(stream, { end: false });
          child.stderr.pipe(stream.stderr, { end: false });
          stream.pipe(child.stdin);
          child.on('error', () => { stream.exit(127); stream.end(); });
          child.on('close', (code) => { stream.exit(code); stream.end(); });
          return;
        }
        stream.on('end', () => {
          if (options.hang) return;
          stream.write('remote stdout\n');
          stream.stderr.write('remote stderr\n');
          stream.exit(options.exitCode || 0);
          stream.end();
        });
      });
    }));
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  context.after(async () => {
    for (const connection of connections) connection.end();
    await new Promise((resolve) => server.close(resolve));
  });
  const stdout = new PassThrough();
  const stderr = new PassThrough();
  let output = '';
  stdout.on('data', (chunk) => { output += chunk.toString(); });
  stderr.on('data', (chunk) => { output += chunk.toString(); });
  return {
    config: { host: '127.0.0.1', port: server.address().port, username: 'fixture', password, hostFingerprint, script },
    observed, stdout, stderr, output: () => output,
  };
}

test('exec argv is fixed; full secret-bearing script is delivered only on stdin', async (context) => {
  const f = await fixture(context);
  await deploy(f.config, f.stdout, f.stderr);
  assert.deepEqual(f.observed.commands, ['bash -se']);
  assert.equal(f.observed.input, `{\n${script}} </dev/null\n`);
  assert.equal(f.output(), 'remote stdout\nremote stderr\n');
  assert.ok(!f.output().includes('fixture $()'));
});

test('wrong host fingerprint rejects before authentication or script delivery', async (context) => {
  const f = await fixture(context);
  await assert.rejects(deploy({ ...f.config, hostFingerprint: `SHA256:${'A'.repeat(43)}` }, f.stdout, f.stderr), /connection failed/);
  assert.equal(f.observed.authenticated, false);
  assert.deepEqual(f.observed.commands, []);
  assert.equal(f.observed.input, '');
});

test('missing fingerprint and empty credentials fail before connecting', async () => {
  const config = { host: '127.0.0.1', username: 'fixture', password, script };
  await assert.rejects(deploy(config), /host fingerprint/);
  await assert.rejects(deploy({ ...config, hostFingerprint, password: '' }), /configuration is incomplete/);
});

test('remote failure propagates without including the script or credentials', async (context) => {
  const f = await fixture(context, { exitCode: 7 });
  await assert.rejects(deploy(f.config, f.stdout, f.stderr), (error) => {
    assert.match(error.message, /remote deployment failed/);
    assert.ok(!error.message.includes(password));
    assert.ok(!error.message.includes(script));
    return true;
  });
});

test('deployment timeout closes the SSH connection', async (context) => {
  const f = await fixture(context, { hang: true });
  await assert.rejects(deploy({ ...f.config, timeoutMs: 1000 }, f.stdout, f.stderr), /timed out/);
});

const bash = process.platform === 'win32' ? process.env.MIGRATION_TEST_BASH : '/bin/bash';

test('real shell: stdin-consuming child cannot swallow later checks or heredocs', { skip: !bash }, async (context) => {
  const f = await fixture(context, { bash });
  await deploy({ ...f.config, script: "printf 'before\\n'\ncat >/dev/null\nprintf 'after\\n'\ncat <<'PAYLOAD'\nliteral $() `text`\nPAYLOAD\nprintf 'final-smoke-check\\n'\n" }, f.stdout, f.stderr);
  assert.equal(f.output(), 'before\nafter\nliteral $() `text`\nfinal-smoke-check\n');
});

test('real shell: failed check after stdin-consuming child fails deployment', { skip: !bash }, async (context) => {
  const f = await fixture(context, { bash });
  await assert.rejects(deploy({ ...f.config, script: "cat >/dev/null\nfalse\nprintf 'must-not-run\\n'\n" }, f.stdout, f.stderr), /remote deployment failed/);
  assert.ok(!f.output().includes('must-not-run'));
});

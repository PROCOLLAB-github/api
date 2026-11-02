const { Client } = require('ssh2');
const { createHash } = require('node:crypto');
const fs = require('node:fs');

// Public ED25519 keys already trusted in the owner's Windows known_hosts.
// The dev server key is deliberately absent.
const trustedKeys = new Set([
  'SHA256:zsdhcHGxocYksE6KyAmlG0hPdtdIU4uE04g2WWGZUHA',
  'SHA256:a+re/FT9OaJs/A06Iwqra4sQPiEOWnoU4f2oYJcbs7Y',
  'SHA256:S2fELiIUBNq+EuEmsH+k+C8wTqlID+ETbaaInNwg5EI',
]);
const ssh = new Client();
let finished = false;
const finish = (code, message) => {
  if (finished) return;
  finished = true;
  clearTimeout(timer);
  ssh.end();
  if (message) process.stderr.write(message + '\n');
  process.exitCode = code;
};
const timer = setTimeout(() => { finish(1, 'Read-only production preflight timed out'); ssh.destroy(); }, 120000);
ssh.on('error', () => finish(1, 'Read-only production SSH connection failed'));
ssh.on('close', () => { if (!finished) finish(1, 'Read-only production SSH closed early'); });
ssh.on('ready', () => {
  ssh.exec('python3 -', (error, stream) => {
    if (error) return finish(1, 'Read-only production probe could not start');
    stream.on('data', chunk => process.stdout.write(chunk));
    stream.stderr.on('data', () => {});
    stream.on('error', () => finish(1, 'Read-only production probe stream failed'));
    stream.on('close', code => finish(code === 0 ? 0 : 1));
    stream.end(fs.readFileSync('.github/scripts/prod_preflight.py'));
  });
});
ssh.connect({
  host: process.env.SERVER_HOST,
  username: process.env.SERVER_USER,
  password: process.env.SERVER_PASSWORD,
  algorithms: { serverHostKey: ['ssh-ed25519'] },
  hostVerifier: key => {
    const value = 'SHA256:' + createHash('sha256').update(key).digest('base64').replace(/=+$/, '');
    const accepted = trustedKeys.has(value);
    process.stdout.write('PROD_SSH_TRUSTED_HOST_KEY=' + accepted + '\n');
    if (!accepted) process.stdout.write('PROD_SSH_UNRECOGNIZED_PUBLIC_KEY=' + value + '\n');
    return accepted;
  },
  readyTimeout: 20000,
  keepaliveInterval: 15000,
});

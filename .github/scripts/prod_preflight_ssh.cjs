const { Client } = require('ssh2');
const fs = require('node:fs');
const { fingerprint, trustedHostKeys, algorithms } = require('./prod_host_trust.cjs');

// Only keys already trusted for this exact hostname can authorize authentication.
const trustedKeys = trustedHostKeys(process.env.PROD_EXISTING_KNOWN_HOSTS, process.env.SERVER_HOST);
if (!trustedKeys.size || !algorithms(trustedKeys).length) {
  process.stdout.write('PROD_EXISTING_HOST_KEY_ANCHOR_FOUND=false\n');
  process.exit(2);
}
process.stdout.write('PROD_EXISTING_HOST_KEY_ANCHOR_FOUND=true\n');
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
  algorithms: { serverHostKey: algorithms(trustedKeys) },
  hostVerifier: key => {
    const value = fingerprint(key);
    const accepted = trustedKeys.has(value);
    process.stdout.write('PROD_SSH_TRUSTED_HOST_KEY=' + accepted + '\n');
    if (!accepted) process.stdout.write('PROD_SSH_UNRECOGNIZED_PUBLIC_KEY=' + value + '\n');
    return accepted;
  },
  readyTimeout: 20000,
  keepaliveInterval: 15000,
});

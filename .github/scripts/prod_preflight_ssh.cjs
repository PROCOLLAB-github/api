const { Client } = require('ssh2');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const dns = require('node:dns').promises;
const net = require('node:net');
const { fingerprint, trustedHostKeys, algorithms } = require('./prod_host_trust.cjs');

const operation = process.env.PROD_DEPENDENCY_OPERATION || 'check';
if (!['discover', 'check', 'backup'].includes(operation)) throw new Error('Invalid production operation');

async function configuredHostKeys() {
  let keys = trustedHostKeys(process.env.PROD_EXISTING_KNOWN_HOSTS, process.env.SERVER_HOST);
  const targets = net.isIP(process.env.SERVER_HOST) ? [process.env.SERVER_HOST] : (await dns.lookup(process.env.SERVER_HOST, {all:true})).map(row => row.address);
  const apiAddresses = (await dns.lookup('api.procollab.ru', {all:true})).map(row => row.address);
  const publicApiMatch = targets.some(host => apiAddresses.includes(host));
  if (!keys.size && publicApiMatch) {
    // Existing trust can use the canonical DNS name while SERVER_HOST uses its IP.
    keys = trustedHostKeys(process.env.PROD_EXISTING_KNOWN_HOSTS, 'api.procollab.ru');
  }
  return {keys, publicApiMatch};
}

async function main() {
  if (operation === 'discover') {
    // No account password or private key is provided to discovery.
    const scan = spawnSync('ssh-keyscan', ['-T', '8', '-t', 'ed25519', process.env.SERVER_HOST], {encoding: 'utf8', env: {PATH: process.env.PATH}, timeout: 15000});
    const values = new Set((scan.stdout || '').split(/\r?\n/).filter(row => row && !row.startsWith('#')).map(row => fingerprint(Buffer.from(row.trim().split(/\s+/)[2] || '', 'base64'))));
    if (scan.status || values.size !== 1) throw new Error('Production public-key discovery failed');
    const trust = await configuredHostKeys();
    console.log('PROD_CONFIGURED_TARGET_MATCHES_PUBLIC_API=' + trust.publicApiMatch);
    console.log('PROD_CANDIDATE_MATCHES_EXISTING_GITHUB_KEY=' + trust.keys.has([...values][0]));
    console.log('PROD_CANDIDATE_ED25519_FINGERPRINT=' + [...values][0]);
    console.log('PROD_DISCOVERY_AUTHENTICATION_ATTEMPTED=false');
    return;
  }

  const {keys} = await configuredHostKeys();
  const approved = process.env.PROD_CONFIRMED_SSH_HOST_KEY_SHA256 || '';
  if (approved) {
    if (!/^SHA256:[A-Za-z0-9+/]{43}$/.test(approved)) throw new Error('Invalid confirmed production host key');
    keys.set(approved, 'ssh-ed25519');
  }
  if (!keys.size || !algorithms(keys).length) {
    console.log('PROD_EXISTING_HOST_KEY_ANCHOR_FOUND=false');
    throw new Error('Production host key is not confirmed; authentication was not attempted');
  }
  if (!process.env.PROD_EXPECTED_DATABASE_NAME) throw new Error('Expected production database configuration is missing');
  const encodedName = Buffer.from(process.env.PROD_EXPECTED_DATABASE_NAME).toString('base64');
  console.log('::add-mask::' + encodedName);
  const probe = fs.readFileSync('.github/scripts/prod_preflight.py').toString('base64');
  let script = 'import base64,sys,types\n' +
    'module=types.ModuleType("prod_preflight")\n' +
    'module.EXPECTED_DATABASE_NAME_B64=' + JSON.stringify(encodedName) + '\n' +
    'sys.modules["prod_preflight"]=module\n' +
    'exec(compile(base64.b64decode(' + JSON.stringify(probe) + '),"<prod-readonly-preflight>","exec"),module.__dict__)\n';
  if (operation === 'backup') {
    const backup = fs.readFileSync('.github/scripts/prod_backup.py').toString('base64');
    script += 'exec(compile(base64.b64decode(' + JSON.stringify(backup) + '),"<prod-protected-backup>","exec"),globals())\n';
  } else script += 'module.main()\n';

  await new Promise((resolve, reject) => {
    const ssh = new Client();
    let finished = false;
    const finish = error => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      ssh.end();
      error ? reject(error) : resolve();
    };
    const timer = setTimeout(() => { finish(new Error('Production operation timed out')); ssh.destroy(); }, operation === 'backup' ? 50 * 60 * 1000 : 120000);
    ssh.on('error', () => finish(new Error('Production SSH connection failed')));
    ssh.on('close', () => { if (!finished) finish(new Error('Production SSH closed early')); });
    ssh.on('ready', () => {
      ssh.exec('timeout --signal=TERM --kill-after=20s 45m python3 -', (error, stream) => {
        if (error) return finish(new Error('Production operation could not start'));
        stream.on('data', chunk => process.stdout.write(chunk));
        // stderr can contain credentials from third-party tools; only safe structured markers leave the server.
        stream.stderr.on('data', () => {});
        stream.on('error', () => finish(new Error('Production operation stream failed')));
        stream.on('close', code => finish(code === 0 ? null : new Error('Production operation failed; inspect safe markers')));
        stream.end(script);
      });
    });
    ssh.connect({
      host: process.env.SERVER_HOST,
      username: process.env.SERVER_USER,
      password: process.env.SERVER_PASSWORD,
      algorithms: {serverHostKey: algorithms(keys)},
      hostVerifier: key => {
        const accepted = keys.has(fingerprint(key));
        console.log('PROD_SSH_TRUSTED_HOST_KEY=' + accepted);
        return accepted;
      },
      readyTimeout: 20000,
      keepaliveInterval: 15000,
    });
  });
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });

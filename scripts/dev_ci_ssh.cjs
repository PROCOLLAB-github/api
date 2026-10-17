// Keep deployment secrets out of the remote shell's command-line arguments.
const { createHash } = require('node:crypto');
const { Client } = require('ssh2');

function fingerprint(key) {
  return `SHA256:${createHash('sha256').update(key).digest('base64').replace(/=+$/, '')}`;
}

function validate(config) {
  for (const name of ['host', 'username', 'password', 'script']) {
    if (typeof config[name] !== 'string' || !config[name].trim()) {
      throw new Error('DEV SSH configuration is incomplete');
    }
  }
  if (!/^SHA256:[A-Za-z0-9+/]{43}$/.test(config.hostFingerprint || '')) {
    throw new Error('DEV SSH host fingerprint is missing or invalid');
  }
}

async function deploy(config, stdout = process.stdout, stderr = process.stderr) {
  validate(config);
  return new Promise((resolve, reject) => {
    const client = new Client();
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      client.end();
      if (error) reject(error);
      else resolve();
    };
    const timer = setTimeout(() => {
      finish(new Error('DEV SSH deployment timed out'));
      client.destroy();
    }, config.timeoutMs || 30 * 60 * 1000);

    client.on('error', () => finish(new Error('DEV SSH connection failed')));
    client.on('close', () => finish(new Error('DEV SSH connection closed before completion')));
    client.on('ready', () => {
      // Only this fixed command appears in sshd/bash argv. The script travels on stdin.
      client.exec('bash -se', (error, stream) => {
        if (error) return finish(new Error('DEV SSH command could not start'));
        stream.on('data', (chunk) => stdout.write(chunk));
        stream.stderr.on('data', (chunk) => stderr.write(chunk));
        stream.on('error', () => finish(new Error('DEV SSH command stream failed')));
        stream.on('close', (code, signal) => {
          if (code === 0 && !signal) finish();
          else finish(new Error('DEV remote deployment failed; inspect masked command output'));
        });
        stream.end(config.script.endsWith('\n') ? config.script : `${config.script}\n`);
      });
    });
    try {
      client.connect({
        host: config.host,
        port: config.port || 22,
        username: config.username,
        password: config.password,
        // DEV's pinned public host key is ED25519. Never accept another key implicitly.
        algorithms: { serverHostKey: ['ssh-ed25519'] },
        hostVerifier: (key) => fingerprint(key) === config.hostFingerprint,
        readyTimeout: 20000,
        keepaliveInterval: 15000,
      });
    } catch {
      finish(new Error('DEV SSH connection configuration failed'));
    }
  });
}

if (require.main === module) {
  deploy({
    host: process.env.DEV_SERVER_HOST,
    username: process.env.DEV_SERVER_USER,
    password: process.env.DEV_SERVER_PASSWORD,
    hostFingerprint: process.env.DEV_SSH_HOST_KEY_SHA256,
    script: process.env.DEV_DEPLOY_SCRIPT,
  }).catch((error) => {
    // All errors above are fixed messages, without credentials, script or stack.
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { deploy, fingerprint };

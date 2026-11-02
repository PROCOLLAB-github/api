const { createHash, createHmac, timingSafeEqual } = require('node:crypto');

function fingerprint(key) {
  return 'SHA256:' + createHash('sha256').update(key).digest('base64').replace(/=+$/, '');
}

function matches(pattern, host) {
  if (pattern.startsWith('|1|')) {
    const parts = pattern.split('|');
    if (parts.length !== 4) return false;
    const expected = Buffer.from(parts[3], 'base64');
    const actual = createHmac('sha1', Buffer.from(parts[2], 'base64')).update(host).digest();
    return expected.length === actual.length && timingSafeEqual(expected, actual);
  }
  const expression = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.');
  return new RegExp('^' + expression + '$', 'i').test(host);
}

function trustedHostKeys(knownHosts, host) {
  const keys = new Map();
  const revoked = new Set();
  for (const line of (knownHosts || '').split(/\r?\n/)) {
    const fields = line.trim().split(/\s+/);
    const marker = fields[0]?.startsWith('@') ? fields.shift() : '';
    if (fields.length < 3 || fields[0].startsWith('#') || marker === '@cert-authority') continue;
    const names = fields[0].split(',');
    if (names.some(name => name.startsWith('!') && matches(name.slice(1), host))) continue;
    if (!names.some(name => !name.startsWith('!') && matches(name, host))) continue;
    const value = fingerprint(Buffer.from(fields[2], 'base64'));
    if (marker === '@revoked') revoked.add(value);
    else keys.set(value, fields[1]);
  }
  for (const value of revoked) keys.delete(value);
  return keys;
}

function algorithms(keys) {
  const types = new Set(keys.values());
  return [
    ...(types.has('ssh-ed25519') ? ['ssh-ed25519'] : []),
    ...[...types].filter(type => type.startsWith('ecdsa-sha2-')),
    ...(types.has('ssh-rsa') ? ['rsa-sha2-512', 'rsa-sha2-256'] : []),
  ];
}

module.exports = { fingerprint, trustedHostKeys, algorithms };

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHmac } = require('node:crypto');
const { fingerprint, trustedHostKeys, algorithms } = require('./prod_host_trust.cjs');
const key = Buffer.from('synthetic-public-key-wire');
const encoded = key.toString('base64');
test('missing or different host anchors cannot authorize the key', () => {
  assert.equal(trustedHostKeys('', 'prod.example.invalid').size, 0);
  assert.equal(trustedHostKeys('dev.example.invalid ssh-ed25519 ' + encoded, 'prod.example.invalid').size, 0);
});
test('matching existing hostname key is accepted with its exact fingerprint', () => {
  const keys = trustedHostKeys('prod.example.invalid ssh-ed25519 ' + encoded, 'prod.example.invalid');
  assert.equal(keys.get(fingerprint(key)), 'ssh-ed25519');
  assert.deepEqual(algorithms(keys), ['ssh-ed25519']);
});
test('hashed OpenSSH hostnames are matched without exposing their contents', () => {
  const salt = Buffer.from('synthetic-salt');
  const hash = createHmac('sha1', salt).update('prod.example.invalid').digest('base64');
  const row = '|1|' + salt.toString('base64') + '|' + hash + ' ssh-rsa ' + encoded;
  assert.equal(trustedHostKeys(row, 'prod.example.invalid').size, 1);
  assert.equal(trustedHostKeys(row, 'dev.example.invalid').size, 0);
  assert.deepEqual(algorithms(trustedHostKeys(row, 'prod.example.invalid')), ['rsa-sha2-512', 'rsa-sha2-256']);
});
test('revocation and negative hostname rules override positive entries', () => {
  assert.equal(trustedHostKeys('*.example.invalid,!prod.example.invalid ssh-ed25519 ' + encoded, 'prod.example.invalid').size, 0);
  const row = 'prod.example.invalid ssh-ed25519 ' + encoded;
  assert.equal(trustedHostKeys(row + '\n@revoked ' + row, 'prod.example.invalid').size, 0);
});


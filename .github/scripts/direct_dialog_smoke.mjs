import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';

const path = process.argv[2];
const { origin, chat, accounts: [sender, recipient] } = JSON.parse(await readFile(path, 'utf8'));
assert.equal(origin, 'https://dev.procollab.ru');
const route = `/chats/directs/${chat}/`;
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFElEQVR4nGNsYGhgIASYCKoY9ooAMHcBEEgyj5EAAAAASUVORK5CYII=', 'base64');
const marker = randomUUID();

async function request(user, path, expected, options = {}) {
  const headers = new Headers(options.headers);
  if (user) headers.set('Authorization', `Bearer ${user.access}`);
  const response = await fetch(new URL(path, origin), { ...options, headers, signal: AbortSignal.timeout(20000) });
  assert.equal(response.status, expected, `${options.method ?? 'GET'} ${path.split('?')[0]} status`);
  return response;
}

async function upload(name) {
  const body = new FormData();
  body.set('file', new Blob([png], { type: 'image/png' }), name);
  const response = await request(sender, '/files/?scope=direct_chat', 201, { method: 'POST', body });
  return (await response.json()).url;
}

async function socket(user) {
  const connection = new WebSocket(new URL('/ws/chat/', origin.replace(/^http/, 'ws')), ['Bearer', user.access]);
  const received = [];
  connection.addEventListener('message', ({ data }) => received.push(JSON.parse(data)));
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('WebSocket open timeout')), 8000);
    connection.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    connection.addEventListener('error', () => { clearTimeout(timer); reject(new Error('WebSocket open failed')); }, { once: true });
  });
  return {
    received,
    send: (payload) => connection.send(JSON.stringify(payload)),
    close: () => connection.close(),
    async next(uuid) {
      for (let step = 0; step < 80; step++) {
        const event = received.find(({ type, content }) => type === 'new_message' && content?.message?.client_message_id === uuid);
        if (event) return event.content;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      throw new Error(`Message ACK absent. Event types: ${received.map(({ type }) => type).join(', ')}`);
    },
  };
}

function payload(text, fileUrls = []) {
  return {
    type: 'new_message',
    content: { chat_type: 'direct', chat_id: chat, client_message_id: randomUUID(), text, file_urls: fileUrls },
  };
}

let author;
let viewer;
try {
  const urls = [await upload('direct-qa-first.png'), await upload('direct-qa-second.png')];
  const storageResponses = await Promise.all(urls.map((url) =>
    fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(10000) })
  ));
  const nonPrivate = storageResponses.filter(({ status }) => ![401, 403, 404].includes(status)).length;
  console.log(`Selectel direct access: ${storageResponses.map(({ status }) => status).join(', ')}`);
  await Promise.all(storageResponses.map(({ body }) => body?.cancel()));
  author = await socket(sender);
  viewer = await socket(recipient);
  const original = payload(`Проверка ${marker}`, urls);
  author.send(original);
  const { message: first, is_replay: firstReplay } = await viewer.next(original.content.client_message_id);
  assert.equal(firstReplay, false);
  author.close();
  author = await socket(sender);
  author.send(original);
  const { message: repeated, is_replay: repeat } = await author.next(original.content.client_message_id);
  assert.equal(repeat, true);
  assert.equal(first.id, repeated.id);
  assert.equal(first.files.length, 2);
  for (const { link } of first.files) {
    assert.ok(link.startsWith(route));
    assert.deepEqual(Buffer.from(await (await request(recipient, link, 200)).arrayBuffer()), png);
    await request(null, link, 401);
  }
  const newer = payload(`Более новое сообщение ${marker}`);
  author.send(newer);
  await viewer.next(newer.content.client_message_id);
  const history = await (await request(recipient, `${route}messages/`, 200)).json();
  assert.equal(history.results.filter(({ client_message_id }) => client_message_id === original.content.client_message_id).length, 1);
  assert.equal(viewer.received.filter(({ content }) => content?.message?.id === first.id).length, 1);
  await request(recipient, `${route}report-spam/`, 204, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: first.id }),
  });
  await writeFile(`${path}.api-selected`, String(first.id), { mode: 0o600 });
  console.log(JSON.stringify({ selected: first.id, images: first.files.length, idempotent: true, report: 204 }));
  assert.equal(nonPrivate, 0, 'Selectel privacy check requires a denied or missing response');
} finally {
  author?.close();
  viewer?.close();
}

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright-core');
const fixturePath = process.argv[2];
const { origin, chat, accounts: [author, recipient] } = JSON.parse(await readFile(fixturePath, 'utf8'));
const localUi = process.env.DIRECT_DIALOG_LOCAL_UI;
assert.ok(localUi ? origin.startsWith('http://127.0.0.1:') && localUi.startsWith('http://127.0.0.1:')
  : origin === 'https://dev.procollab.ru');
const url = `${localUi || origin}/office/chats/${chat}`;
const screenshots = process.argv[3];
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAwAAAAICAIAAABChommAAAAFElEQVR4nGNsYGhgIASYCKoY9ooAMHcBEEgyj5EAAAAASUVORK5CYII=', 'base64');
const sample = randomUUID().slice(0, 8);
const message = `Фотографии на проверку ${sample}`;
const singleText = `Одна фотография ${sample}`;
const retryText = `Сообщение после повтора ${sample}`;
const actionsLabel = 'Действия с сообщением';
const reportLabel = 'Пожаловаться на спам';

const browser = await chromium.launch({ channel: 'chrome', headless: true, executablePath: process.env.DIRECT_DIALOG_CHROME });
let retryPayload;
let retryAttempts = 0;
let replayObserved = false;
let allowAck = false;

async function setup(user, mobile = false) {
  const context = await browser.newContext({
    viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    isMobile: mobile,
    hasTouch: mobile,
  });
  await context.addCookies(Object.entries({ devAccessToken: user.access, devRefreshToken: user.refresh })
    .map(([name, value]) => ({ name, value, url: localUi || origin })));
  await context.addInitScript(() => localStorage.setItem('cookieConsent', 'declined'));
  if (localUi) {
    await context.route('https://dev.procollab.ru/**', async (route) => {
      const { pathname, search } = new URL(route.request().url());
      const response = await route.fetch({ url: origin + pathname + search });
      await route.fulfill({ response });
    });
  }
  return context;
}

function localSocket(client, user) {
  const connection = new WebSocket(new URL('/ws/chat/', origin.replace(/^http/, 'ws')), ['Bearer', user.access]);
  const queue = [];
  connection.addEventListener('open', () => queue.splice(0).forEach((message) => connection.send(message)));
  connection.addEventListener('close', ({ code, reason }) => client.close({ code: code === 1006 ? 1011 : code, reason }));
  client.onClose(() => connection.close());
  return {
    send(data) {
      if (connection.readyState === WebSocket.OPEN) connection.send(data);
      else queue.push(data);
    },
    onMessage(listener) { connection.addEventListener('message', ({ data }) => listener(data)); },
  };
}

try {
  const desktop = await setup(author);
  await desktop.routeWebSocket('**/ws/chat/', (client) => {
    const server = localUi ? localSocket(client, author) : client.connectToServer();
    client.onMessage((data) => {
      const event = JSON.parse(String(data));
      if (event.type === 'new_message' && event.content?.text === retryText) {
        const uuid = event.content.client_message_id;
        assert.match(uuid, /^[0-9a-f-]{36}$/);
        if (retryPayload) assert.deepEqual(event.content, retryPayload);
        retryPayload = event.content;
        retryAttempts += 1;
      }
      server.send(data);
    });
    server.onMessage((data) => {
      const event = JSON.parse(String(data));
      if (event.type === 'new_message' && event.content?.message?.text === retryText) {
        if (!allowAck) return;
        replayObserved = event.content.is_replay === true;
      }
      client.send(data);
    });
  });
  const mobile = await setup(recipient, true);
  if (localUi) {
    await mobile.routeWebSocket('**/ws/chat/', (client) => {
      const server = localSocket(client, recipient);
      client.onMessage((data) => server.send(data));
      server.onMessage((data) => client.send(data));
    });
  }
  const desktopPage = await desktop.newPage();
  const mobilePage = await mobile.newPage();
  for (const [screen, page] of [['desktop', desktopPage], ['mobile', mobilePage]]) {
    page.on('response', async (response) => {
      if (new URL(response.url()).pathname !== '/files/' || response.request().method() !== 'POST') return;
      const body = await response.json().catch(() => ({}));
      console.log(`${screen} attachment upload: status=${response.status()} url=${typeof body?.url === 'string'}`);
    });
    page.on('requestfailed', (request) => {
      if (new URL(request.url()).pathname === '/files/') console.log(`${screen} attachment transport failed`);
    });
  }
  await Promise.all([desktopPage.goto(url), mobilePage.goto(url)]);
  const composer = desktopPage.getByRole('textbox', { name: 'Сообщение', exact: true });
  await composer.waitFor({ timeout: 25000 });
  await mobilePage.getByRole('textbox', { name: 'Сообщение', exact: true }).waitFor({ timeout: 25000 });
  await composer.fill(message);
  await desktopPage.locator('input[type=file]').setInputFiles(
    ['first.png', 'second.png'].map((name) => ({ name, mimeType: 'image/png', buffer: png }))
  );
  await desktopPage.getByRole('button', { name: 'Отправить', exact: true }).click();

  const messageRow = (page, text) => page.locator('[id^=direct-message-]').filter({ hasText: text });
  const photo = { name: 'Открыть изображение first.png', exact: true };
  const mobilePhoto = messageRow(mobilePage, message).getByRole('button', photo);
  await mobilePhoto.waitFor({ timeout: 25000 });
  const desktopPhoto = messageRow(desktopPage, message).getByRole('button', photo);
  await Promise.all([desktopPhoto.scrollIntoViewIfNeeded(), mobilePhoto.scrollIntoViewIfNeeded()]);
  await Promise.all([desktopPhoto.locator('img').waitFor(), mobilePhoto.locator('img').waitFor()]);
  await mkdir(screenshots, { recursive: true });
  await mobilePage.screenshot({ path: join(screenshots, 'mobile-images.png') });
  await mobilePhoto.click();
  await mobilePage.getByRole('button', { name: 'Следующее изображение', exact: true }).click();
  const download = mobilePage.waitForEvent('download');
  await mobilePage.getByText('Скачать', { exact: true }).click();
  const original = await download;
  assert.equal(original.suggestedFilename(), 'second.png');
  assert.deepEqual(await readFile(await original.path()), png);
  const gallery = mobilePage.getByRole('dialog');
  await gallery.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await gallery.waitFor({ state: 'hidden' });

  await mobilePage.getByRole('textbox', { name: 'Сообщение', exact: true }).fill(singleText);
  await mobilePage.locator('input[type=file]').setInputFiles({ name: 'single.png', mimeType: 'image/png', buffer: png });
  await mobilePage.getByRole('button', { name: 'Отправить', exact: true }).click();
  const singlePhoto = messageRow(desktopPage, singleText).getByRole('button', {
    name: 'Открыть изображение single.png', exact: true,
  });
  await singlePhoto.scrollIntoViewIfNeeded();
  await singlePhoto.locator('img').waitFor();
  await composer.fill(retryText);
  await desktopPage.locator('input[type=file]').setInputFiles({ name: 'retry.png', mimeType: 'image/png', buffer: png });
  await desktopPage.getByRole('button', { name: 'Отправить', exact: true }).click();
  await mobilePage.getByText(retryText, { exact: true }).waitFor({ timeout: 15000 });
  const retry = desktopPage.getByRole('button', { name: 'Повторить', exact: true });
  await retry.waitFor({ timeout: 20000 });
  allowAck = true;
  await retry.click();
  const confirmed = desktopPage.locator('[id^=direct-message-]').getByText(retryText, { exact: true });
  await confirmed.waitFor({ timeout: 10000 });
  assert.equal(replayObserved, true);
  assert.equal(retryAttempts, 2);
  for (const page of [desktopPage, mobilePage]) {
    assert.equal(await page.getByText(retryText, { exact: true }).count(), 1);
  }

  const selected = messageRow(mobilePage, message);
  const id = (await selected.getAttribute('id')).replace('direct-message-', '');
  await selected.getByRole('button', { name: actionsLabel, exact: true }).click();
  await mobilePage.getByText(reportLabel, { exact: true }).click();
  const confirmation = mobilePage.getByRole('dialog');
  await confirmation.getByText(message, { exact: true }).waitFor();
  assert.equal(await confirmation.getByText(retryText, { exact: true }).count(), 0);
  await desktopPage.screenshot({ path: join(screenshots, 'desktop.png') });
  await mobilePage.screenshot({ path: join(screenshots, 'mobile-report.png') });
  const response = mobilePage.waitForResponse((reply) => reply.url().endsWith('/report-spam/') && reply.request().method() === 'POST');
  await confirmation.getByRole('button', { name: 'Отправить жалобу', exact: true }).click();
  const report = await response;
  assert.equal(report.status(), 204);
  assert.equal(String(report.request().postDataJSON().message_id), id);
  await writeFile(`${fixturePath}.browser-selected`, id, { mode: 0o600 });
  console.log('Chrome desktop/mobile: two images, download, lost ACK and deduplicated retry, exact selected report.');
} finally {
  await browser.close();
}

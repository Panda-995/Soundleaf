const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const root = 'http://127.0.0.1:8781';
const signIn = require('./login.cjs');
const novel = Array.from({ length: 40 }, (_, i) => `${i + 1}.章节标题内容${i}`).join('\n');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await signIn(page, root, 'hover-test-password');
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts'));
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: '悬停验证.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByLabel('书名', { exact: true }).waitFor();
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.waitForTimeout(800);
  const books = await (await page.request.get(root + '/api/books')).json();
  if (!books.length) throw Error('no book');
  await page.evaluate(id => localStorage.setItem('soundleaf-book', id), books[0].id);
  await page.goto(root + '/#director');
  await page.getByLabel('朗读文本').waitFor();
  const list = page.locator('.director-layout .chapter-items');
  const metrics = async () =>
    list.evaluate(el => ({
      sw: el.scrollWidth, cw: el.clientWidth,
      sh: el.scrollHeight, ch: el.clientHeight,
    }));
  // Let entrance animations settle before taking the baseline.
  await page.waitForTimeout(600);
  const before = await metrics();
  // Hover the last visible item and hold the mouse there, sampling stability.
  const last = list.locator('button').last();
  await last.scrollIntoViewIfNeeded();
  const box = await last.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const samples = [];
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(120);
    samples.push(await metrics());
    // Keep the mouse over whatever item is under the cursor now (post-shift position).
  }
  const unstable = samples.some(m => m.sw !== before.sw || m.sh !== before.sh || m.ch !== before.ch);
  if (unstable) throw Error('hover causes layout instability: ' + JSON.stringify({ before, samples }));
  if (before.sw > before.cw) throw Error('horizontal overflow exists: ' + JSON.stringify(before));
  console.log(JSON.stringify({ errors, before, last: samples[samples.length - 1] }));
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });

const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const root = 'http://127.0.0.1:8781';
const out = path.resolve('output/runtime/ui-audit');
const signIn = require('./login.cjs');
const novel = Array.from({ length: 12 }, (_, i) => `这是第${i + 1}段的正文内容，用来验证试听页的滚动行为是否正确，段落要有足够的长度。`).join('\n');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await signIn(page, root, 'browser-test-password');
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts'));
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: '滚动验证.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.waitForTimeout(600);
  const books = await (await page.request.get(root + '/api/books')).json();
  const bookId = books[0].id;
  const book = await (await page.request.get(root + '/api/books/' + bookId)).json();
  const H = { 'X-Soundleaf': '1' };
  for (const c of book.chapters) {
    const j = await page.request.post(root + `/api/books/${bookId}/generate`, { headers: H, data: { chapter_ids: [c.id] } });
    if (j.status() !== 200) throw Error('generate failed ' + j.status());
  }
  for (let i = 0; i < 80; i++) {
    const jobs = await (await page.request.get(root + '/api/jobs')).json();
    if (jobs.jobs.length && jobs.jobs.every(j => ['succeeded', 'cancelled'].includes(j.status))) break;
    await new Promise(r => setTimeout(r, 500));
  }
  await page.evaluate(id => localStorage.setItem('soundleaf-book', id), bookId);
  await page.reload();
  await page.locator('.sidebar').waitFor();
  await page.goto(root + '/#listen');
  await page.locator('.listen-book .chapter-items button').first().click();
  await page.locator('.reading-scroll').waitFor();
  await page.waitForTimeout(400);
  const pageScrolls = await page.evaluate(() => { window.scrollTo(0, 400); return window.scrollY > 0; });
  if (pageScrolls) throw Error('page scrolls on listen route');
  const before = await page.evaluate(() => document.querySelector('.reading-scroll').scrollTop);
  await page.evaluate(() => document.querySelector('.reading-scroll').scrollTo(0, 300));
  const after = await page.evaluate(() => document.querySelector('.reading-scroll').scrollTop);
  if (!(after > before)) throw Error('reading region does not scroll');
  const asideTop = await page.evaluate(() => document.querySelector('.listen-book').getBoundingClientRect().top);
  if (asideTop < 0) throw Error('aside moved: ' + asideTop);
  const strip = await page.evaluate(() => {
    const el = document.querySelector('.now-segment');
    if (!el) return null;
    return el.getBoundingClientRect().top - document.querySelector('.reading-scroll').getBoundingClientRect().top;
  });
  if (strip === null || strip > 40) throw Error('strip not pinned: ' + strip);
  // The chapter text must own at least two thirds of the stage height.
  const share = await page.evaluate(() => {
    const stage = document.querySelector('.listen-stage').getBoundingClientRect().height;
    const reading = document.querySelector('.reading-scroll').getBoundingClientRect().height;
    return reading / stage;
  });
  if (share < 0.66) throw Error('reading share too small: ' + share.toFixed(2));
  console.log('reading share:', share.toFixed(2));
  console.log(JSON.stringify({ errors, before, after, asideTop, strip }));
  await page.screenshot({ path: path.join(out, 'listen-scroll.png') });
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });

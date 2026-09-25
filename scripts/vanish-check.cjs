const { chromium } = require('../frontend/node_modules/playwright');
const root = 'http://127.0.0.1:8781';
const signIn = require('./login.cjs');
const novel = Array.from({ length: 40 }, (_, i) => `第${i + 1}章 章节标题${i + 1}\n这是第${i + 1}章的正文内容，用来验证章节列表切换。`)
  .join('\n');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await signIn(page, root, 'vanish-test-password');
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts'));
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: '消失验证.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByLabel('书名', { exact: true }).waitFor();
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.waitForTimeout(800);
  const books = await (await page.request.get(root + '/api/books')).json();
  await page.evaluate(id => localStorage.setItem('soundleaf-book', id), books[0].id);
  await page.goto(root + '/#director');
  await page
    .getByLabel('朗读文本')
    .waitFor({ timeout: 15000 })
    .catch(async e => {
      await page.screenshot({ path: 'output/runtime/screenshots/vanish-debug.png', fullPage: true });
      console.error('hash=', await page.evaluate(() => location.hash),
        'bookId=', await page.evaluate(() => localStorage.getItem('soundleaf-book')),
        'body=', (await page.evaluate(() => document.body.innerText)).slice(0, 300));
      throw e;
    });
  await page.waitForTimeout(600);
  const list = page.locator('.director-layout .chapter-items');
  const count = await list.locator('button').count();
  if (count < 25) throw Error('expected 25+ chapters, got ' + count);
  const opacities = () =>
    list.locator('button').evaluateAll(els => els.map(e => +getComputedStyle(e).opacity));
  // Click the last chapter (nth-child >= 18, the delay band) and watch every
  // item's opacity: none may drop towards zero after the click.
  const last = list.locator('button').last();
  await last.scrollIntoViewIfNeeded();
  await last.click();
  let minOpacity = 1;
  for (let i = 0; i < 14; i++) {
    await page.waitForTimeout(100);
    const values = await opacities();
    minOpacity = Math.min(minOpacity, ...values);
  }
  if (minOpacity < 0.9) throw Error('chapter item vanished: min opacity ' + minOpacity);
  // Switch back to an early chapter as well.
  await list.locator('button').first().click();
  await page.waitForTimeout(700);
  const values = await opacities();
  if (Math.min(...values) < 0.9) throw Error('item vanished on second switch');
  console.log(JSON.stringify({ errors, count, minOpacity }));
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });

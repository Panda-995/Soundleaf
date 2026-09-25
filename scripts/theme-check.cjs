const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const fs = require('fs');
const root = 'http://127.0.0.1:8781';
const out = path.resolve('output/runtime/screenshots');
const signIn = require('./login.cjs');
fs.mkdirSync(out, { recursive: true });
const novel = `第一章 雾中的信\n暮色落进海面的时候，林舟收到了一封没有署名的信。\n信封上的字迹很淡，像是被海风吹散了一半。\n第二章 灯塔来客\n他沿着旧码头向前走。灯塔亮起的那一刻，远处有人轻轻叫了他的名字。\n“你还是来了。”沈雾站在门边，声音比夜色更轻。`;
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await signIn(page, root, 'theme-test-password');
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts'));
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: '主题验证.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByLabel('书名', { exact: true }).waitFor();
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.getByLabel('选择全部章节').waitFor();
  await page.getByLabel('选择全部章节').check();
  const genPost = page.waitForResponse(r => r.url().endsWith('/generate') && r.request().method() === 'POST');
  await page.getByRole('button', { name: /生成所选/ }).click();
  await page.getByRole('button', { name: '确认生成', exact: true }).click();
  if ((await genPost).status() !== 200) throw Error('generate');
  for (let i = 0; i < 60; i++) {
    const jobs = await (await page.request.get(root + '/api/jobs')).json();
    if (jobs.jobs.length && jobs.jobs.every(j => ['succeeded', 'cancelled'].includes(j.status))) break;
    await page.waitForTimeout(500);
  }
  // Dark theme screenshots
  await page.goto(root + '/#library');
  await page.locator('main h1').first().waitFor();
  await page.screenshot({ path: path.join(out, 'theme-dark-library.png') });
  await page.goto(root + '/#director');
  await page.getByLabel('朗读文本').waitFor();
  await page.screenshot({ path: path.join(out, 'theme-dark-director.png') });
  // Toggle to light via the sidebar button
  await page.getByRole('button', { name: '切换到亮色模式' }).click();
  if (await page.evaluate(() => document.documentElement.dataset.theme) !== 'light') throw Error('theme toggle');
  const stored = await page.evaluate(() => localStorage.getItem('soundleaf-theme'));
  if (stored !== 'light') throw Error('theme persist');
  await page.screenshot({ path: path.join(out, 'theme-light-library.png') });
  await page.goto(root + '/#director');
  await page.getByLabel('朗读文本').waitFor();
  await page.screenshot({ path: path.join(out, 'theme-light-director.png') });
  await page.goto(root + '/#listen');
  // Start playback so audioMeta/timeline loads, then paragraphs become buttons.
  await page.locator('.listen-book .chapter-items button').first().click();
  await page.locator('.reading-text button').first().waitFor();
  await page.screenshot({ path: path.join(out, 'theme-light-listen.png') });
  // Click the third paragraph (if present) and verify playback seeks there
  const paras = page.locator('.reading-text button');
  const count = await paras.count();
  if (count >= 2) {
    await page.waitForFunction(() => { const a = document.querySelector('audio'); return a && a.readyState >= 1; });
    const target = paras.nth(count - 1);
    const expected = await target.evaluate(b => {
      const meta = window.__nothing; return null; // placeholder
    });
    const before = await page.locator('audio').evaluate(a => a.currentTime);
    await target.click();
    await page.waitForTimeout(400);
    const after = await page.locator('audio').evaluate(a => a.currentTime);
    if (!(after > before + 0.2)) throw Error(`seek did not move: ${before} -> ${after}`);
    console.log('SEEK OK:', before, '->', after);
  }
  // Reload and confirm the light theme survived
  await page.reload();
  await page.locator('.sidebar').waitFor();
  if (await page.evaluate(() => document.documentElement.dataset.theme) !== 'light') throw Error('theme lost after reload');
  console.log(JSON.stringify({ errors, seekChecked: count }));
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });

const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const root = 'http://127.0.0.1:8781';
const out = path.resolve('output/runtime/screenshots');
const signIn = require('./login.cjs');
const novel = `第一章 雾中的信\n暮色落进海面的时候，林舟收到了一封没有署名的信。\n信封上的字迹很淡，像是被海风吹散了一半。\n第二章 灯塔来客\n他沿着旧码头向前走。灯塔亮起的那一刻，远处有人轻轻叫了他的名字。\n“你还是来了。”沈雾站在门边，声音比夜色更轻。`;
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await signIn(page, root, 'switch-test-password');
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts'));
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: '切换验证.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByLabel('书名', { exact: true }).waitFor();
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.getByLabel('选择全部章节').waitFor();
  await page.goto(root + '/#director');
  await page.getByLabel('朗读文本').waitFor();
  // The full-page loading state must not exist outside the initial mount.
  if (await page.locator('main > .loading').count()) throw Error('loading state visible after mount');
  // Click chapter 2 in the nav: heading updates instantly, script dims in place.
  // Slow the API deliberately so the in-place transition becomes observable.
  await page.route('**/api/chapters/*', async route => {
    await new Promise(r => setTimeout(r, 600));
    await route.continue();
  });
  await page.locator('.chapter-nav .chapter-items button').nth(1).click();
  await page.waitForTimeout(120);
  const switching = await page.locator('.script-panel.switching').count();
  const headTitle = await page.locator('main h1').first().innerText();
  const navStillVisible = await page.locator('.chapter-nav .chapter-items button').count();
  const inspectorStillVisible = await page.locator('.inspector').count();
  if (!switching) throw Error('switching state not applied');
  if (!headTitle.includes('灯塔来客')) throw Error('heading did not switch instantly: ' + headTitle);
  if (navStillVisible < 2 || !inspectorStillVisible) throw Error('layout was wiped during switch');
  // The switched-in chapter item must keep a normal height (no .loading collision).
  const itemBox = await page.locator('.chapter-nav .chapter-items button').nth(1).boundingBox();
  if (!itemBox || itemBox.height > 80) throw Error('chapter item stretched: ' + (itemBox && itemBox.height));
  // Header buttons must not flicker into a disabled state during switching.
  for (const name of ['重新载入', '生成本章']) {
    if (await page.getByRole('button', { name }).evaluate(b => b.disabled)) throw Error(name + ' disabled during switch');
  }
  await page.screenshot({ path: path.join(out, 'switch-transition.png') });
  // New content arrives; dimming clears.
  await page.waitForFunction(() => !document.querySelector('.script-panel.switching'));
  const body = await page.locator('.script-body').innerText();
  if (!body.includes('你还是来了')) throw Error('chapter 2 content not loaded');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(out, 'switch-settled.png') });
  console.log(JSON.stringify({ errors, switching, headTitle, navStillVisible, inspectorStillVisible }));
  await browser.close();
  if (errors.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });

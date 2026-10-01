// One-off UI state previewer: renders states the standard smoke/audit never
// reach (cross-engine binding banner, download error) and screenshots them.
const { chromium } = require('../frontend/node_modules/playwright');
const http = require('http');
const path = require('path');
const fs = require('fs');
const signIn = require('./login.cjs');
const root = 'http://127.0.0.1:8782';
const out = path.resolve('output/runtime/ui-preview');
fs.mkdirSync(out, { recursive: true });

// Mini MiniMax mock: /get_voice returns one system voice so the binding
// whitelist accepts male-qn-qingse while the book is on the cloud engine.
const mock = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({
    base_resp: { status_code: 0 },
    system_voice: [{ voice_id: 'male-qn-qingse', voice_name: '青涩青年', description: ['男声'] }],
  }));
});

(async () => {
  await new Promise((r) => mock.listen(18782, '127.0.0.1', r));
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 1024 }, reducedMotion: 'reduce' });
  await page.goto(root);
  await signIn(page, root, 'preview-password');
  await page.locator('.sidebar').waitFor();
  const api = page.request;
  const H = { 'X-Soundleaf': '1' };
  const put = (url, data) => api.put(root + url, { data, headers: H });
  // 1) 云端配置 + 导入书 + 绑定旁白/角色，然后切到本地引擎 → 角色库告警条
  const saved = await put('/api/settings/tts', { provider: 'minimax', base_url: 'http://127.0.0.1:18782/v1', model: 'speech-2.6-hd', voice: 'male-qn-qingse', allow_local: true });
  if (saved.status() !== 200) throw Error('settings save ' + saved.status());
  const imp = await api.post(root + '/api/imports', { multipart: { file: { name: 'novel.txt', mimeType: 'text/plain', buffer: Buffer.from('第一章 台球\n“站住。”他说。\n他拦住了她。\n') } }, headers: H });
  const impData = await imp.json();
  const confirmed = await api.post(root + '/api/imports/confirm', { data: { id: impData.id, title: '雾海来信', chapters: impData.chapters }, headers: H });
  const bookId = (await confirmed.json())['id'];
  const refreshed = await api.post(root + '/api/voices/refresh', { headers: H });
  if (refreshed.status() !== 200) throw Error('refresh ' + refreshed.status());
  if ((await put(`/api/books/${bookId}`, { voice: 'male-qn-qingse' })).status() !== 200) throw Error('narrator bind');
  if ((await put(`/api/books/${bookId}/cast`, { speaker: '他', voice: 'male-qn-qingse' })).status() !== 200) throw Error('cast bind');
  if ((await put('/api/settings/tts', { provider: 'local' })).status() !== 200) throw Error('switch local');
  await page.evaluate((id) => localStorage.setItem('soundleaf-book', id), bookId);
  await page.goto(root + '/#cast');
  await page.reload(); // goto alone is a hash change; App state needs the fresh book id
  await page.getByText('个音色绑定来自其他语音服务').waitFor();
  await page.screenshot({ path: path.join(out, 'cast-banner-dark-1536.png'), fullPage: true });
  await page.evaluate(() => localStorage.setItem('soundleaf-theme', 'light'));
  await page.reload();
  await page.getByText('个音色绑定来自其他语音服务').waitFor();
  await page.screenshot({ path: path.join(out, 'cast-banner-light-1536.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'cast-banner-light-390.png'), fullPage: true });
  await page.setViewportSize({ width: 1536, height: 1024 });
  await page.evaluate(() => localStorage.setItem('soundleaf-theme', 'dark'));
  await page.reload();
  // 2) 触发下载（坏镜像 → 快速重试后失败）→ 错误态
  await page.goto(root + '/#settings');
  await page.getByText('本地模型', { exact: true }).waitFor();
  await page.getByRole('button', { name: '下载', exact: true }).first().click();
  await page.getByText('下载失败', { exact: false }).first().waitFor({ timeout: 90000 });
  await page.waitForTimeout(2500); // 等最后一次重试写完 error 文案
  await page.screenshot({ path: path.join(out, 'settings-download-error-dark-1536.png'), fullPage: true });
  // 3) 音色库本地目录 + 克隆表单（亮色）
  await page.goto(root + '/#voices');
  await page.getByText('克隆音色', { exact: true }).waitFor();
  await page.evaluate(() => localStorage.setItem('soundleaf-theme', 'light'));
  await page.reload();
  await page.getByText('克隆音色', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(out, 'voices-local-light-1536.png'), fullPage: true });
  await browser.close();
  mock.close();
  console.log('UI PREVIEW OK');
})().catch(async (e) => { console.error(e); process.exit(1); });

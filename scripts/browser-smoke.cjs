const { chromium } = require('../frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const signIn = require('./login.cjs');
const root = 'http://127.0.0.1:8781';
const out = path.resolve('output/runtime/screenshots');
fs.mkdirSync(out, { recursive: true });
const novel = `第一章 雾中的信\n暮色落进海面的时候，林舟收到了一封没有署名的信。\n信封上的字迹很淡，像是被海风吹散了一半。\n第二章 灯塔来客\n他沿着旧码头向前走。灯塔亮起的那一刻，远处有人轻轻叫了他的名字。\n“你还是来了。”沈雾站在门边，声音比夜色更轻。\n第三章 海的另一边\n林舟没有回答。他把那封信放在桌上，等着窗外的雨慢慢停下来。`;
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  const page = await browser.newPage({ viewport: { width: 1536, height: 1024 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const checks = [];
  const waitJobs = async () => {
    for (let i = 0; i < 80; i++) {
      const data = await (await page.request.get(root + '/api/jobs')).json();
      if (data.jobs.some(j => ['failed', 'needs_review'].includes(j.status))) throw Error(JSON.stringify(data.jobs));
      if (data.jobs.length && data.jobs.every(j => ['succeeded', 'cancelled'].includes(j.status))) return;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw Error('Queue did not finish');
  };
  await page.goto(root);
  await page.getByLabel('用户名').waitFor();
  await page.screenshot({ path: path.join(out, '00-login.png'), fullPage: true });
  // Fresh fixtures carry the seeded admin/admin account; the first login is
  // forced through the default-password change dialog (screenshot included).
  await signIn(page, root, 'browser-test-password', {
    onDialog: (dialog) => page.screenshot({ path: path.join(out, '00-first-password.png'), fullPage: true }),
  });
  await page.locator('.sidebar').waitFor();
  checks.push('Default admin login and forced first password change');
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  const saved = page.waitForResponse(r => r.url().endsWith('/api/settings/tts') && r.request().method() === 'PUT');
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  if ((await saved).status() !== 200) throw Error('Settings save');
  await page.getByRole('button', { name: '测试已保存的配置' }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts/test'));
  checks.push('Real HTTP provider catalogue connection');
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: '雾海来信-集成测试.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByLabel('书名', { exact: true }).waitFor();
  await page.getByLabel('作者', { exact: true }).fill('集成测试 · 非真实语音');
  await page.screenshot({ path: path.join(out, '02-import.png'), fullPage: true });
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.getByLabel('选择全部章节').waitFor();
  await page.getByLabel('选择全部章节').check();
  await page.getByRole('button', { name: /生成所选/ }).click();
  const firstGenerate = page.waitForResponse(r => r.url().endsWith('/generate') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '确认生成', exact: true }).click();
  if ((await firstGenerate).status() !== 200) throw Error('Queue generation');
  await page.waitForURL('**/#queue');
  await waitJobs();
  checks.push('TXT import → persisted chapters → queued synthesis → FFmpeg assembly');
  await page.goto(root + '/#chapters');
  await page.locator('tbody tr').first().getByRole('button', { name: /试听/ }).click();
  await page.waitForFunction(() => document.querySelector('audio').currentTime > 0);
  await page.getByRole('combobox', { name: '播放倍速' }).click();
  await page.getByRole('option', { name: '1.5×', exact: true }).click();
  if (await page.locator('audio').evaluate(a => a.playbackRate) !== 1.5) throw Error('Playback rate');
  checks.push('Authenticated audio playback and 1.5x speed');
  await page.locator('audio').evaluate(a => a.pause());
  const bookId = await page.evaluate(() => localStorage.getItem('soundleaf-book'));
  const audioId = await page.locator('audio').evaluate(a => a.src.split('/').pop());
  const progress = await page.request.put(root + '/api/books/' + bookId + '/progress', {
    headers: { 'X-Soundleaf': '1' }, data: { audio_id: audioId, seconds: 0.7 }
  });
  if (progress.status() !== 200) throw Error('Save listening progress');
  await page.goto(root + '/#listen');
  await page.reload();
  await page.getByRole('button', { name: '继续上次播放' }).click();
  await page.waitForFunction(() => document.querySelector('audio').currentTime >= 0.7);
  await page.locator('audio').evaluate(a => a.pause());
  checks.push('Listening progress restored after page reload');
  for (const [route, title] of [['library','01-library'],['chapters','03-chapters'],['director','04-director'],['voices','05-voices'],['queue','06-queue'],['listen','07-listen'],['export','08-export'],['settings','09-settings']]) {
    await page.goto(root + '/#' + route);
    await page.locator('main h1').first().waitFor();
    if (route === 'listen') await page.locator('.reading-text').first().waitFor();
    if (route === 'director') await page.getByLabel('朗读文本').waitFor();
    await page.screenshot({ path: path.join(out, title + '.png'), fullPage: true });
  }
  await page.goto(root + '/#director');
  await page.getByLabel('朗读文本').fill('这一句经过了修改，只重新制作受影响的片段。');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.waitForResponse(r => /\/api\/chapters\//.test(r.url()) && r.request().method() === 'PUT');
  checks.push('Director text revision save');
  await page.goto(root + '/#export');
  await page.getByRole('button', { name: '全选已完成' }).click();
  await page.getByLabel('允许导出尚未更新的旧音频').check();
  await page.getByRole('button', { name: '创建导出包' }).click();
  const exportPost = page.waitForResponse(r => r.url().endsWith('/exports') && r.request().method() === 'POST');
  await page.waitForURL('**/#queue');
  if ((await exportPost).status() !== 200) throw Error('Queue export');
  await waitJobs();
  await page.goto(root + '/#export');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: '下载', exact: true }).first().click();
  const download = await downloadPromise;
  await download.saveAs(path.resolve('output/runtime/browser-export.zip'));
  checks.push('Version-aware ZIP export and browser download');
  await page.goto(root + '/#settings');
  await page.getByRole('button', { name: 'AI 分析', exact: true }).click();
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  const aiSaved = page.waitForResponse(r => r.url().endsWith('/api/settings/ai') && r.request().method() === 'PUT');
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  if ((await aiSaved).status() !== 200) throw Error('AI settings save');
  await page.goto(root + '/#chapters');
  await page.getByRole('button', { name: 'AI 识别章节', exact: true }).click();
  await page.getByRole('button', { name: '查看分章预览' }).waitFor();
  // Leaving the page must not lose the persisted preview.
  await page.goto(root + '/#voices');
  await page.goto(root + '/#chapters');
  await page.getByRole('button', { name: '查看分章预览' }).click();
  await page.getByRole('dialog').getByRole('checkbox').check();
  await page.screenshot({ path:path.join(out,'10-ai-chapters.png'),fullPage:true });
  await page.getByRole('button', { name: /确认分章 ·/ }).click();
  await page.getByRole('dialog').waitFor({ state:'hidden' });
  checks.push('AI boundary preview survives navigation and applies original source');
  await page.goto(root + '/#director');
  await page.locator('.chapter-nav .chapter-items button').nth(1).click();
  await page.getByLabel('朗读文本').waitFor();
  await page.getByRole('button', { name: 'AI 优化分段' }).click();
  await page.getByText('AI 建议的分段').waitFor();
  await page.screenshot({ path: path.join(out, '11-ai-restructure.png'), fullPage: true });
  const adopted = page.waitForResponse(r => /\/api\/chapters\/[a-f0-9]+$/.test(r.url()) && r.request().method() === 'PUT');
  await page.getByRole('button', { name: '采纳 AI 分段并替换现有脚本' }).click();
  if ((await adopted).status() !== 200) throw Error('Adopt AI resegmentation');
  const refreshed = await (await page.request.get(root + '/api/books/' + bookId)).json();
  const restructured = await (await page.request.get(root + '/api/chapters/' + refreshed.chapters[1].id)).json();
  if (restructured.segments.map(s => s.text).join('') !== restructured.source) throw Error('Resegmentation broke source text');
  if (restructured.segments.length < 2) throw Error('Resegmentation was not adopted');
  checks.push('AI semantic resegmentation preview adopted with source intact');
  await page.getByRole('button', { name: 'AI 分析本章' }).click();
  await page.getByRole('button', { name: '采纳角色、音色与朗读建议' }).waitFor();
  await page.screenshot({path:path.join(out,'11-ai-director.png'),fullPage:true});
  await page.getByRole('button', { name: '采纳角色、音色与朗读建议' }).click();
  await page.getByRole('combobox', {name:'为沈雾选择音色'}).waitFor();
  const voiceSelect=page.getByRole('combobox', {name:'为沈雾选择音色'});
  await voiceSelect.focus();
  await page.keyboard.press('ArrowDown');
  await page.getByRole('listbox').waitFor();
  await page.screenshot({path:path.join(out,'12-unified-select.png'),fullPage:true});
  await page.keyboard.press('Escape');
  if(!await voiceSelect.evaluate(e=>e===document.activeElement)) throw Error('Dropdown focus did not return');
  const scriptSaved=page.waitForResponse(r=>r.url().includes('/api/chapters/')&&r.request().method()==='PUT');
  await page.getByRole('button',{name:'保存',exact:true}).click();
  const script=await (await scriptSaved).json();
  if(new Set(script.segments.map(s=>s.voice)).size<2) throw Error('Distinct voices were not saved');
  if(!script.segments.some(s=>s.speaker==='沈雾')) throw Error('Dialogue speaker lost');
  await page.getByRole('button',{name:'生成本章',exact:true}).click();
  const chapterGenerate = page.waitForResponse(r => r.url().endsWith('/generate') && r.request().method() === 'POST');
  await page.getByRole('button',{name:'确认生成',exact:true}).click();
  if ((await chapterGenerate).status() !== 200) throw Error('Queue chapter generation');
  await waitJobs();
  checks.push('Paragraph/dialogue AI suggestions → two saved voices → chapter generation');
  checks.push('Custom select keyboard navigation, Escape and focus restoration');

  const layouts = [];
  for (const width of [1536, 1024, 390]) {
    await page.setViewportSize({ width, height: 960 });
    for (const route of ['library','import','chapters','director','voices','queue','listen','export','settings']) {
      await page.goto(root + '/#' + route);
      await page.locator('main h1').first().waitFor();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      layouts.push({ route, width, overflow });
      if (width === 390 && ['library','director','listen'].includes(route)) await page.screenshot({ path: path.join(out, route + '-mobile.png'), fullPage: true });
    }
  }
  await page.goto(root + '/#library');
  // Each round deletes one book, then waits for the books list to actually
  // refresh before touching the next card. Clicking a stale card would fire a
  // DELETE for an already-removed book (404) and leave the confirm dialog
  // stuck open, deadlocking the loop.
  const deleteFirstBook = async (expectResponse) => {
    const btn = page.getByRole('button', { name: /删除《/ }).first();
    const label = await btn.getAttribute('aria-label');
    const response = expectResponse
      ? page.waitForResponse(r => r.url().includes('/api/books/') && r.request().method() === 'DELETE')
      : null;
    await btn.click();
    await page.getByRole('button', { name: '确认删除', exact: true }).click();
    if (response) {
      const del = await response;
      if (del.status() !== 200) throw Error('Delete book request returned ' + del.status());
    }
    await page.locator('dialog[open]').waitFor({ state: 'hidden', timeout: 10000 });
    // Duplicated book titles share one aria-label; wait for the count to drop.
    const before = await page.getByRole('button', { name: /删除《/ }).count();
    for (let i = 0; label && before && i < 40; i++) {
      const n = await page.getByRole('button', { name: /删除《/ }).count();
      if (n < before) break;
      await page.waitForTimeout(250);
    }
    await page.waitForTimeout(250);
  };
  await deleteFirstBook(true);
  // Remove any leftover books from earlier runs so the empty state is reached.
  while (await page.getByRole('button', { name: /删除《/ }).count()) {
    await deleteFirstBook(false);
  }
  await page.getByText('第一本有声书，从这里开始', { exact: true }).waitFor();
  await page.reload();
  await page.getByText('第一本有声书，从这里开始', {exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'13-library-after-delete.png'),fullPage:true});
  if((await (await page.request.get(root+'/api/books')).json()).length) throw Error('Book not deleted');
  checks.push('Delete book removes it from library and survives reload without stale selection');
  const report = { checks, errors, layouts, note: 'Local HTTP fixture returns synthetic WAV data, not real speech. Screenshots use isolated test data.' };
  fs.writeFileSync('output/runtime/browser-verification.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  await browser.close();
  if (errors.length || layouts.some(l => l.overflow)) process.exitCode = 1;
})().catch(error => { console.error(error); process.exit(1); });

const assert = require('node:assert/strict');
const { chromium } = require('../frontend/node_modules/playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const workspace = path.resolve(__dirname, '..');
const dist = path.join(workspace, 'frontend/dist');
const output = path.join(workspace, 'output/runtime/editor-regressions.json');
fs.mkdirSync(path.dirname(output), { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const server = http.createServer((req, res) => {
  const file = path.join(dist, req.url.split('?')[0] === '/' ? 'index.html' : req.url.split('?')[0]);
  try { const b = fs.readFileSync(file); res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'); res.end(b); }
  catch { res.writeHead(404); res.end(); }
});
const seg = text => ({ text, voice: '', emotion: 'neutral', speaker: '旁白', speed: 1, pause: 250 });
const chapter = () => ({ id: 'c1', book_id: 'b1', title: '第一章', position: 1, revision: 1, active_audio: null, audio_revision: null, duration: 0, characters: 5, segments: [seg('原始正文')], source: '原始正文', suggestion: null, restructure: { segments: [seg('原始正文')], existing_revision: 1 }, versions: [], marks: [] });
const book = () => ({ id: 'b1', title: '隔离审查书籍', author: '', cover: null, voice: '', chapters: [chapter()], completed: 0 });
const settings = { tts: { voice: 'test', provider: 'openai', base_url: '', model: '' }, ai: { provider: 'openai', base_url: '', model: '' }, favorites: [], paused: false, data_dir: 'test', free_bytes: 999999999, total_bytes: 9999999999 };
(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const root = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: true });
  const results = [];
  async function create(route = 'director', config = {}) {
    const page = await browser.newPage({ viewport: { width: 1536, height: 1024 }, reducedMotion: 'reduce' });
    page.on('pageerror', e => console.error('PAGEERROR', e.message));
    page.on('console', msg => { if (msg.type() === 'error') console.error('CONSOLE', msg.text()); });
    await page.addInitScript(() => localStorage.setItem('soundleaf-book', 'b1'));
    const state = { chapter: chapter(), requests: [], holdSave: null, releaseSave: null, releaseAudio: null, currentJob: 'old', newJobDone: false };
    page.on('dialog', d => d.accept());
    await page.route('**/api/**', async r => {
      const u = new URL(r.request().url()).pathname.slice(4), method = r.request().method();
      state.requests.push({ u, method });
      let out = {};
      if (u === '/bootstrap') out = { authenticated: true, mustChangePassword: false };
      else if (u === '/books') out = [{ ...book(), chapters: 1 }, ...(config.audio ? [{ ...book(), id: 'b2', title: '第二本书', chapters: 1 }] : [])];
      else if (u === '/books/b1') out = config.audio ? { ...book(), chapters: [{ ...chapter(), active_audio: 'a1', duration: 10 }] } : book();
      else if (u === '/books/b2') out = { ...book(), id: 'b2', title: '第二本书', chapters: [{ ...chapter(), id: 'c2', title: '第二本书章节', book_id: 'b2' }] };
      else if (u === '/audio/a1/metadata') { await new Promise(resolve => { state.releaseAudio = resolve; }); out = { id: 'a1', chapter_id: 'c1', duration: 10, peaks: [], timeline: [{ index: 0, start: 0, end: 10 }] }; }
      else if (u === '/settings') out = settings;
      else if (u === '/voices') out = { voices: [{ id: 'test', name: '测试音色' }], favorites: [], emotion: true };
      else if (u === '/books/b1/dict') out = [];
      else if (u === '/chapters/c1/dismiss-restructure') state.chapter.restructure = null;
      else if (u === '/chapters/c1' && method === 'PUT') {
        const body = r.request().postDataJSON();
        assert.equal(body.revision, state.chapter.revision, 'Save must use the latest server revision');
        if (config.holdSave) await new Promise(resolve => { state.releaseSave = resolve; });
        state.chapter = { ...state.chapter, ...body, revision: state.chapter.revision + 1 };
        out = state.chapter;
      }
      else if (u === '/chapters/c1') out = state.chapter;
      else if (u === '/jobs') out = { jobs: config.analysis ? [{ id: state.currentJob, book_id: 'b1', chapter_id: null, kind: 'analyze_chapters', status: state.currentJob === 'old' || state.newJobDone ? 'succeeded' : 'running' }] : [] };
      else if (u === '/jobs/old') out = { id: 'old', status: 'succeeded', proposed: [{ title: '旧结果', text: '原始正文' }], total: 1, done: 1, stage: '旧任务完成' };
      else if (u === '/jobs/new') out = { id: 'new', status: state.newJobDone ? 'succeeded' : 'running', proposed: state.newJobDone ? [{ title: '新结果', text: '原始正文' }] : null, total: 1, done: state.newJobDone ? 1 : 0, stage: state.newJobDone ? '新任务完成' : '新任务运行中' };
      else if (u === '/books/b1/analyze-chapters') { state.currentJob = 'new'; out = { id: 'new' }; }
      await r.fulfill({ json: out });
    });
    await page.goto(root + '/#' + route);
    await sleep(1000);
    return { page, state };
  }
  try {
    {
      const { page, state } = await create();
      await page.locator('.inspector textarea').fill('不应丢失的未保存正文');
      await page.getByRole('button', { name: '忽略本次建议', exact: true }).click();
      await page.getByRole('button', { name: '忽略本次建议', exact: true }).waitFor({ state: 'hidden' });
      assert.equal(await page.locator('.inspector textarea').inputValue(), '不应丢失的未保存正文');
      assert.equal(await page.getByRole('button', { name: '保存', exact: true }).isDisabled(), false);
      results.push({ case: 'dismiss_suggestion_preserves_draft', textAfter: await page.locator('.inspector textarea').inputValue(), requests: state.requests.filter(r => r.method !== 'GET'), dirtyNoticeStillPresent: await page.getByText('有尚未保存的调整。保存后再生成；切换章节前请先保存。', { exact: true }).count() });
      await page.close();
    }
    {
      const { page, state } = await create('director', { holdSave: true });
      await page.locator('.inspector textarea').fill('点击保存时的正文');
      await page.getByRole('button', { name: '保存', exact: true }).click();
      for (let tries = 0; !state.releaseSave && tries < 200; tries++) await sleep(10);
      assert.ok(state.releaseSave, "Save request did not start");
      await page.locator('.inspector textarea').fill('保存请求期间继续输入的正文');
      const whileSaving = await page.locator('.inspector textarea').inputValue();
      state.releaseSave();
      await sleep(250);
      assert.equal(await page.locator('.inspector textarea').inputValue(), whileSaving);
      assert.equal(await page.getByRole('button', { name: '保存', exact: true }).isDisabled(), false);
      state.releaseSave = null;
      await page.getByRole('button', { name: '保存', exact: true }).click();
      for (let tries = 0; !state.releaseSave && tries < 200; tries++) await sleep(10);
      assert.ok(state.releaseSave, "Save request did not start");
      state.releaseSave();
      await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '保存' && b.disabled));
      assert.equal(state.chapter.segments[0].text, whileSaving);
      results.push({ case: 'save_preserves_subsequent_edits', whileSaving, textAfter: await page.locator('.inspector textarea').inputValue(), serverText: state.chapter.segments[0].text, saveDisabled: await page.getByRole('button', { name: '保存', exact: true }).isDisabled() });
      await page.close();
    }
    {
      const { page, state } = await create('chapters', { analysis: true });
      await page.getByRole('button', { name: '重新识别章节', exact: true }).waitFor();
      await page.getByRole('button', { name: '重新识别章节', exact: true }).click();
      await page.getByText('新任务运行中', { exact: false }).waitFor();
      state.newJobDone = true;
      await page.getByText('新任务完成', { exact: false }).waitFor({ timeout: 8000 });
      assert.ok(await page.getByRole('button', { name: /查看分章预览/ }).count());
      results.push({ case: 'second_chapter_analysis_refreshes', backendJobStatus: 'succeeded', uiText: await page.locator('.analysis-toolbar').innerText(), newDetailFetchCount: state.requests.filter(r => r.u === '/jobs/new').length, jobsListFetchCount: state.requests.filter(r => r.u === '/jobs').length });
      await page.close();
    }
    {
      const { page, state } = await create('chapters', { audio: true });
      await page.getByRole('button', { name: '试听第一章', exact: true }).click();
      for (let tries = 0; !state.releaseAudio && tries < 200; tries++) await sleep(10);
      assert.ok(state.releaseAudio, "Audio request did not start");
      await page.getByRole('combobox', { name: '当前书籍', exact: true }).click();
      await page.getByRole('option', { name: '第二本书', exact: true }).click();
      await page.getByRole('heading', { name: '第二本书', exact: true }).first().waitFor();
      state.releaseAudio();
      await sleep(250);
      assert.equal(await page.locator('audio').getAttribute('src'), null);
      results.push({ case: 'book_switch_cancels_pending_audio', bookSelection: await page.getByRole('combobox', { name: '当前书籍', exact: true }).innerText(), loadedAudio: await page.locator('audio').getAttribute('src'), playerLabel: await page.locator('.now-playing').innerText() });
      await page.close();
    }
    fs.writeFileSync(output, JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results, null, 2));
  } finally { await browser.close(); server.close(); }
})().catch(e => { console.error(e); server.close(); process.exitCode = 1; });


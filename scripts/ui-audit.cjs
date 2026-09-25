const { chromium } = require('../frontend/node_modules/playwright');
const path = require('path');
const root = 'http://127.0.0.1:8781';
const out = path.resolve('output/runtime/ui-audit');
const signIn = require('./login.cjs');
fs = require('fs');
fs.mkdirSync(out, { recursive: true });
const novel = `第一章 雾中的信\n暮色落进海面的时候，林舟收到了一封没有署名的信。\n“你还是来了。”沈雾站在门边，声音比夜色更轻。\n第二章 灯塔来客\n他沿着旧码头向前走。灯塔亮起的那一刻，远处的海面上传来悠长的汽笛声。`;
const routes = ['library','import','chapters','cast','director','voices','queue','listen','export','settings'];
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1536, height: 960 } });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  const report = { errors, checks: [] };

  await signIn(page, root, 'browser-test-password');
  await page.locator('.sidebar').waitFor({ timeout: 10000 }).catch(async e => {
    await page.screenshot({ path: 'output/runtime/ui-audit/login-fail.png' });
    console.error('body:', (await page.evaluate(() => document.body.innerText)).slice(0, 200));
    throw e;
  });
  await page.goto(root + '/#settings');
  await page.getByLabel('API 基础地址').fill('http://127.0.0.1:18781/v1');
  await page.getByLabel('模型名称').fill('fixture-model');
  await page.getByLabel('默认音色 ID').fill('fixture-calm');
  await page.getByLabel('允许局域网或本地 HTTP 服务').check();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await page.waitForResponse(r => r.url().endsWith('/api/settings/tts'));
  await page.goto(root + '/#import');
  await page.locator('input[type=file]').setInputFiles({ name: 'UI审计.txt', mimeType: 'text/plain', buffer: Buffer.from(novel) });
  await page.getByRole('button', { name: '确认分章并创建' }).click();
  await page.waitForTimeout(600);

  const auditPage = async (label) => {
    for (const theme of ['dark', 'light']) {
      await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
      await page.waitForTimeout(120);
      for (const width of [1536, 1024, 390]) {
        await page.setViewportSize({ width, height: 960 });
        // Longer than the sidebar's 200ms slide-out transition: screenshots
        // taken mid-transition used to show a phantom sidebar sliver.
        await page.waitForTimeout(400);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        if (overflow) report.checks.push(`OVERFLOW ${label} ${theme} ${width}`);
        await page.screenshot({ path: path.join(out, `${label}-${theme}-${width}.png`) });
      }
    }
    await page.setViewportSize({ width: 1536, height: 960 });
  };

  // Sweep every route in both themes and viewports.
  for (const route of routes) {
    await page.goto(root + '/#' + route);
    await page.locator('main h1, .empty, .loading').first().waitFor({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(200);
    await auditPage(route);
  }

  // Interaction details on the director page.
  await page.goto(root + '/#director');
  await page.getByLabel('朗读文本').waitFor();
  // 1. Focus visibility: tab to the first button and check outline.
  await page.keyboard.press('Tab');
  const outline = await page.evaluate(() => {
    const el = document.activeElement;
    const s = getComputedStyle(el);
    return { tag: el.tagName, outline: s.outlineStyle, width: s.outlineWidth };
  });
  if (outline.outline === 'none') report.checks.push('FOCUS outline missing on tab: ' + JSON.stringify(outline));
  // 2. Touch targets at mobile width: all visible buttons >= 40px in the smaller dimension.
  await page.setViewportSize({ width: 390, height: 844 });
  const small = await page.evaluate(() => {
    const bad = [];
    for (const el of document.querySelectorAll('button, .button')) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0 && (r.width < 32 || r.height < 32)) {
        bad.push(`${(el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 12)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
    return bad;
  });
  if (small.length) report.checks.push('TOUCH TARGETS < 32px: ' + small.join(' | '));
  // 3. Reduced motion: animations must be off.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(root + '/#library');
  await page.locator('main h1').first().waitFor();
  const anim = await page.evaluate(() => {
    const el = document.querySelector('main > *');
    return getComputedStyle(el).animationName;
  });
  if (anim !== 'none') report.checks.push('REDUCED MOTION not honored: ' + anim);
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  // 4. WCAG contrast audit: resolve the app's text/surface color pairs from
  // computed styles in BOTH themes, convert oklch→sRGB→relative luminance,
  // and require ≥4.5:1 for body-size text pairs.
  for (const theme of ['dark', 'light']) {
    await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
    await page.waitForTimeout(150);
    const pairs = await page.evaluate(() => {
      const rootStyle = getComputedStyle(document.documentElement);
      const v = name => rootStyle.getPropertyValue(name).trim();
      const parse = c => {
        let m = String(c).match(/oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/);
        if (m) {
          const L = parseFloat(m[1]), C = parseFloat(m[2]), H = parseFloat(m[3]);
          const hr = H * Math.PI / 180;
          const a = C * Math.cos(hr), b = C * Math.sin(hr);
          const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
          const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
          const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
          const lin = x => Math.min(1, Math.max(0, x ** 3));
          return [lin(+4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
                  lin(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
                  lin(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)];
        }
        m = String(c).match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/);
        if (m) {
          const lin = x => { x /= 255; return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
          return [lin(+m[1]), lin(+m[2]), lin(+m[3])];
        }
        return null;
      };
      const lum = rgb => (rgb ? 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2] : null);
      const ratio = (fgName, bgName) => {
        const lf = lum(parse(v(fgName))), lb = lum(parse(v(bgName)));
        if (lf === null || lb === null) return null;
        const hi = Math.max(lf, lb), lo = Math.min(lf, lb);
        return (hi + 0.05) / (lo + 0.05);
      };
      // Self-test vectors: the oklch→sRGB conversion must match Chrome's
      // native values for pure white/black, or every ratio is garbage.
      const white = lum(parse('oklch(1 0 0)')), black = lum(parse('oklch(0 0 0)'));
      const s255 = lin => Math.round((lin <= 0.0031308 ? 12.92 * lin : 1.055 * Math.pow(lin, 1 / 2.4) - 0.055) * 255);
      const wr = s255(white), br = s255(black);
      const selfTestOk = Math.abs(white - 1) <= 1e-6 && black === 0 && br === 0 && wr === 255;
      return {
        selfTestOk,
        selfTestDebug: `white=${white} black=${black} wr=${wr} br=${br}`,
        'text/bg': ratio('--text', '--bg'),
        'text/panel': ratio('--text', '--panel'),
        'text/raised': ratio('--text', '--raised'),
        'muted/bg': ratio('--muted', '--bg'),
        'muted/panel': ratio('--muted', '--panel'),
        'on-lime/lime': ratio('--on-lime', '--lime'),
        'lime-ink/active-bg': ratio('--lime-ink', '--active-bg'),
        'mint/bg': ratio('--mint', '--bg'),
        'red/bg': ratio('--red', '--bg'),
        'warn/bg': ratio('--warn', '--bg'),
      };
    });
    if (pairs.selfTestOk === false) {
      report.checks.push(`CONTRAST ${theme} self-test: ${pairs.selfTestDebug}`);
    }
    delete pairs.selfTestOk;
    delete pairs.selfTestDebug;
    for (const [pair, r] of Object.entries(pairs)) {
      if (r === null) { report.checks.push(`CONTRAST ${theme} ${pair}: unparseable`); continue; }
      if (r < 4.5) report.checks.push(`CONTRAST ${theme} ${pair}: ${r.toFixed(2)}:1 BELOW 4.5`);
    }
  }
  fs.writeFileSync(path.join(out, 'ui-audit.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  // Fail loudly so CI can block UI regressions (overflow, console errors,
  // failed interaction checks).
  if (report.errors.length || report.checks.length) process.exit(1);
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });

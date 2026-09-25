// Shared sign-in for the browser checks against tests/ui_fixture.py.
// The backend seeds admin/admin into a fresh data directory and forces a
// password change on that first login. Checks may run in any order against
// a long-lived fixture, so candidate passwords are probed through the API
// context first (outside the page — a failed in-page attempt would land in
// the browser console and trip the audit's zero-error rule); the real UI
// login then runs with the winning password. Whenever the forced-change
// dialog appears it is completed with `password`, so after a check the
// studio is always protected by that check's own password.
const KNOWN_PASSWORDS = [
  'browser-test-password',
  'hover-test-password',
  'switch-test-password',
  'theme-test-password',
  'vanish-test-password',
];

module.exports = async function signIn(page, root, password, { onDialog } = {}) {
  let current = null;
  for (const candidate of ['admin', password, ...KNOWN_PASSWORDS.filter((p) => p !== password)]) {
    const probe = await page.request.post(root + '/api/login', {
      headers: { 'X-Soundleaf': '1' },
      data: { name: 'admin', password: candidate },
    });
    if (probe.status() === 200) {
      current = candidate;
      break;
    }
  }
  if (!current) throw Error('Could not sign in with any known password');
  // The probe response set a session cookie; drop it so the genuine in-page
  // login flow (which is what these checks exercise) runs from scratch.
  await page.context().clearCookies();
  await page.goto(root);
  await page.getByLabel('用户名').waitFor();
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码', { exact: true }).fill(current);
  const response = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/login')),
    page.getByRole('button', { name: /^登录$/ }).click(),
  ]);
  if (response[0].status() !== 200) throw Error('In-page login failed although the probe succeeded');
  const dialog = page.getByRole('dialog', { name: '请修改默认密码' });
  const forced = await dialog
    .waitFor({ timeout: 3000 })
    .then(() => true)
    .catch(() => false);
  if (!forced) {
    await page.locator('.sidebar').waitFor();
    return;
  }
  if (onDialog) await onDialog(dialog);
  await dialog.getByLabel('当前密码').fill(current);
  await dialog.getByLabel('新密码', { exact: true }).fill(password);
  await dialog.getByLabel('确认新密码').fill(password);
  await dialog.getByRole('button', { name: '保存新密码' }).click();
  await dialog.waitFor({ state: 'hidden' });
  await page.locator('.sidebar').waitFor();
};

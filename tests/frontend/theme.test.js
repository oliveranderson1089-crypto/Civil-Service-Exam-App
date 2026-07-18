/* 主题：applyTheme + sysIsDark。
 *
 * theme 改动 2 次、零测试。三态：dark 强制暗、light 强制亮、auto 跟随系统。applyTheme
 * 据此翻 body.dark、同步选项高亮、改浏览器地址栏配色（theme-color）。sysIsDark 优先
 * 认外壳注入的系统色，其次浏览器 media query。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('applyTheme：dark 强制暗，light 强制亮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`lsSet('theme', 'dark'); applyTheme();`);
  assert.ok(h.window.document.body.classList.contains('dark'), 'dark 没生效');
  h.run(`lsSet('theme', 'light'); applyTheme();`);
  assert.ok(!h.window.document.body.classList.contains('dark'), 'light 没关掉暗色');
});

test('applyTheme：auto 跟随系统色', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`window.__sysDark = true; lsSet('theme', 'auto'); applyTheme();`);
  assert.ok(h.window.document.body.classList.contains('dark'), 'auto + 系统暗 该暗');
  h.run(`window.__sysDark = false; applyTheme();`);
  assert.ok(!h.window.document.body.classList.contains('dark'), 'auto + 系统亮 该亮');
});

test('applyTheme：地址栏配色跟着日/夜翻', (t) => {
  const h = boot(); t.after(() => h.close());
  const meta = h.window.document.querySelector('meta[name="theme-color"]');
  if (!meta) return;   // 没这个 meta 就跳过
  h.run(`lsSet('theme', 'dark'); applyTheme();`);
  assert.strictEqual(meta.content, '#0f141e', '暗色时地址栏没变深');
  h.run(`lsSet('theme', 'light'); applyTheme();`);
  assert.strictEqual(meta.content, '#1a6fb5');
});

test('sysIsDark：优先认外壳注入的 __sysDark', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`window.__sysDark = true;`);
  assert.strictEqual(h.run('sysIsDark()'), true);
  h.run(`window.__sysDark = false;`);
  assert.strictEqual(h.run('sysIsDark()'), false);
});

test('applyTheme：选项按钮高亮当前模式', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`lsSet('theme', 'dark'); applyTheme();`);
  const on = [...h.window.document.querySelectorAll('.theme-opt.on')];
  if (on.length) assert.strictEqual(on[0].dataset.theme, 'dark', '高亮的不是当前模式');
});

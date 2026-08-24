/* 账户与外观：分组（电脑左侧竖栏 / 手机顶部 chips）。
 *
 * 原来八张卡（邮箱 / 密码 / 密保 / 外观 / 朗读 / 外观定制 / 下载 / App）一路铺下去，
 * 改个头像要滚过密码和密保 —— 而这几件事互相之间根本没关系。
 *
 * 这一层就两件事会错，都不会报错、只会静默变难用：
 *   · 分组没真的把别组藏起来（还是一路铺）；
 *   · 藏别组时抢了 hidden 这个类 —— #acct-tts / #acct-app 的 hidden 是别处按
 *     「是不是桌面版」控制的，两边踩同一个类，桌面版的朗读设置会莫名消失。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];
const shown = (h) => $$(h, '#view-account [data-ag]')
  .filter(e => !e.classList.contains('acct-off')).map(e => e.dataset.ag);

test('分组按钮从 data-ag 生成，不是另写一份清单', (t) => {
  const h = boot(); t.after(() => h.close());
  const groups = [...new Set($$(h, '#view-account [data-ag]').map(e => e.dataset.ag))];
  assert.deepStrictEqual($$(h, '#acct-nav [data-agb]').map(b => b.textContent), groups);
  assert.ok(groups.length >= 3, '分组太少，等于没分：' + groups.join('/'));
});

test('一次只显示一组：改个头像不用滚过密码和密保', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("agShow('账号')");
  assert.deepStrictEqual([...new Set(shown(h))], ['账号']);
  h.run("agShow('外观')");
  assert.deepStrictEqual([...new Set(shown(h))], ['外观']);
});

test('藏别组用 acct-off，不许抢 hidden', (t) => {
  const h = boot(); t.after(() => h.close());
  // #acct-tts 的 hidden 由「是不是桌面版」控制；分组要是也用 hidden，两边会互相踩
  h.run("$('#acct-tts').classList.remove('hidden'); agShow('外观');");
  assert.ok(!$(h, '#acct-tts').classList.contains('hidden'),
    '分组切换把 #acct-tts 的 hidden 也动了 —— 桌面版的朗读设置会莫名消失');
  h.run("agShow('账号')");
  assert.ok($(h, '#acct-tts').classList.contains('acct-off'));
  assert.ok(!$(h, '#acct-tts').classList.contains('hidden'), '换组时又去动 hidden 了');
});

test('切组时当前按钮要亮，且只亮一个', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run("agShow('客户端')");
  const on = $$(h, '#acct-nav .on').map(b => b.dataset.agb);
  assert.deepStrictEqual(on, ['客户端']);
});

test('一套分组两种呈现：电脑竖栏、手机 chips，靠断点切', () => {
  const css = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/style.css'), 'utf8');
  assert.match(css, /\.acct-nav\{display:flex;gap:7px;overflow-x:auto/, '手机上不是横向 chips');
  const m = css.match(/@media ?\(min-width:761px\)\{[^@]*?#view-account\{display:grid[\s\S]*?\n\}/);
  assert.ok(m, '电脑上没做成左栏 + 内容两栏');
  assert.match(m[0], /\.acct-nav\{grid-column:1;grid-row:1 \/ span 99;position:sticky/,
    '电脑上导航没固定在左侧');
});

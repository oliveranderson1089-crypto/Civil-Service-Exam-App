/* AI 工具动作：说「已为你打开」之前，得真的打开了。
 *
 * 原先是 try { window[a.fn](); } catch (_) {} 然后**无条件** toast「已为你打开」——
 * 函数一抛异常就被吞掉，用户收到「已为你打开成语积累」，页面纹丝不动。
 * 跟后端 _save_cfg 一个模式：界面说成了，其实没有。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('打开成功才说「已为你打开」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.__opened = 0; window.openIdiom = () => { window.__opened++; };');
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([{ type: "navigate", fn: "openIdiom", label: "成语积累" }])');
  assert.strictEqual(h.window.__opened, 1, '压根没调用目标函数');
  // 不用 deepStrictEqual：toast 对象是在 jsdom 那个 realm 里造的，原型跟 node 的不是同一个，
  // strict 版会因「结构相同但原型不是同一引用」而失败。比字段即可。
  assert.strictEqual(h.toasts.length, 1);
  assert.strictEqual(h.toasts[0].msg, '已为你打开「成语积累」');
  assert.strictEqual(h.toasts[0].err, false);
});

test('打开失败要说没成功，不能还报「已为你打开」', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.openIdiom = () => { throw new Error("界面炸了"); };');
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([{ type: "navigate", fn: "openIdiom", label: "成语积累" }])');
  assert.strictEqual(h.toasts.length, 1);
  assert.match(h.toasts[0].msg, /没成功/, `用户被告知「${h.toasts[0].msg}」，可页面根本没打开`);
  assert.strictEqual(h.toasts[0].err, true, '该是错误样式');
  assert.ok(h.logs.error.length > 0, '得留 console 痕迹，不然没法查是哪个函数炸的');
});

test('AI 给了不存在的函数名时安静跳过（typeof 那道检查还在）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([{ type: "navigate", fn: "根本没这个函数", label: "X" }])');
  assert.strictEqual(h.toasts.length, 0, 'AI 瞎给函数名时不该骗用户说打开了');
});

test('空动作列表不炸', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('stack = [{ view: "home" }];');
  h.run('aiRunActions([])');
  h.run('aiRunActions(null)');
  assert.strictEqual(h.toasts.length, 0);
});

test('工具面板「打开功能」镜像首页卡片，点击像点首页图标一样跳转', (t) => {
  const h = boot(); t.after(() => h.close());
  // 造两张首页卡片：一个板块(section)、一个固定功能
  h.run(`document.querySelector('#home-cards').innerHTML =
    '<div class="home-card" data-go="sec:xingce"><div class="hc-logo">测</div><div class="hc-name">行测</div></div>' +
    '<div class="home-card" data-go="wrongq"><div class="hc-logo"></div><div class="hc-name">错题本</div></div>';`);
  // 打开功能这一组是直接读首页卡片得来的（日后加新卡片自动出现，无需改这里）
  const items = h.plain('aiHomeNavItems()');
  assert.deepStrictEqual(items.map(x => x.label), ['行测', '错题本'], '应镜像首页卡片、保持顺序');
  assert.deepStrictEqual(items.map(x => x.go), ['sec:xingce', 'wrongq']);
  assert.strictEqual(items[0].ic, '测', 'section 用其 CJK 图标');
  assert.strictEqual(items[1].ic, '📓', '固定项用 HOME_IC 映射');

  // 渲染后「打开功能」在最前，含这两项
  h.run('renderAiTools("")');
  const html = h.run("document.querySelector('#ai-tool-list').innerHTML");
  assert.match(html, /打开功能/);
  assert.match(html, /行测/);

  // 点「行测」应走 navHomeCard → openSection('xingce')（stub 掉观察，避免真渲染依赖 SECTIONS）
  h.run('window.__nav = null; openSection = (k) => { window.__nav = k; };');
  h.run(`aiToolRun({ go: 'sec:xingce', label: '行测' })`);
  assert.strictEqual(h.window.__nav, 'xingce', '点打开功能项应像点首页图标一样跳转到对应板块');
  assert.strictEqual(h.toasts[h.toasts.length - 1].msg, '已打开「行测」');
});

/* 确认框这层原来只服务删除，文案写死了「此操作不可撤销」。
   现在写长期记忆也走同一条路——记忆随时能删，照着删除那样吓唬人是错的；
   反过来，删除那句警告一个字都不能少。 */
test('要 AI 记住一件事：确认框问的是记什么，不说「不可撤销」', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.__msg = null; appConfirm = (m) => { window.__msg = m; return Promise.resolve(false); };');
  await h.run(`aiConfirm({ type: 'confirm', tool: 'remember_fact', kind: 'write',
    label: '记住这件事', summary: '目标是四川省考，2026 年 3 月笔试',
    args: { text: '目标是四川省考，2026 年 3 月笔试' } })`);
  const msg = h.window.__msg;
  assert.match(msg, /记住这件事/);
  assert.match(msg, /四川省考/, '得让人看清要记的是哪一句');
  assert.doesNotMatch(msg, /不可撤销/, '记忆随时能删，别照删除那样吓唬人');
  // 页面启动本身会发几条请求，只看确认这条
  assert.strictEqual(h.calls.filter(c => c.url.includes('/confirm')).length, 0,
                     '用户点了取消，就不该真去执行');
});

test('删除仍然照旧警告不可撤销', async (t) => {
  const h = boot(); t.after(() => h.close());
  h.run('window.__msg = null; appConfirm = (m) => { window.__msg = m; return Promise.resolve(false); };');
  await h.run(`aiConfirm({ type: 'confirm', tool: 'delete_note', kind: 'destructive',
    label: '删除小记', summary: '今天背了 20 个成语', args: { id: 3 } })`);
  assert.match(h.window.__msg, /不可撤销/);
  // 老动作没带 kind（服务端还没更新那一刻）：按删除处理，宁可多问一句
  h.run('window.__msg = null;');
  await h.run(`aiConfirm({ type: 'confirm', tool: 'delete_note', label: '删除小记', args: { id: 3 } })`);
  assert.match(h.window.__msg, /不可撤销/);
});

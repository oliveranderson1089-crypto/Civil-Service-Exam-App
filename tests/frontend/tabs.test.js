/* 底部标签栏（界面重构 P0）。
 *
 * 这一层只做导航，不做业务，所以能出错的地方就三类，全在下面盯着：
 *
 *   1) 路由表和真入口走散 —— 条目点下去必须落到 openXxx() 那个真视图。
 *      写死一份「功能清单」是这里最大的隐患：core.js 那边加了板块、改了 key，
 *      标签栏若不跟着变就成了一份僵尸目录，而且**不会报错**，只会点了没反应。
 *      所以专项练的板块是从 BOARD_FEATURES 反查的，这条也测。
 *
 *   2) 栈被越堆越深 —— 标签之间是平级切换。若每切一次就 push 一层，
 *      安卓的实体返回键要按五次才退得出去（用户会以为应用卡死）。
 *
 *   3) 该让位的时候不让位 —— 小记和知识库的悬浮条就贴在 bottom:18px，
 *      做题页要整屏专注。标签栏压上去不会抛异常，只会挡住按钮，
 *      这种「静默变难用」最容易在改版里漏掉，必须由测试钉住。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const $ = (h, sel) => h.window.document.querySelector(sel);
const $$ = (h, sel) => [...h.window.document.querySelectorAll(sel)];
// 标签栏是事件委托，点按钮就够；渲染是同步的，点完立刻能断言
const tap = (h, key) => $(h, `#tabbar [data-tb="${key}"]`).click();

test('五个标签按 TAB_DEFS 的次序生成，不是手写在 index.html 里', (t) => {
  const h = boot(); t.after(() => h.close());
  assert.deepStrictEqual($$(h, '#tabbar [data-tb]').map(b => b.dataset.tb),
    ['today', 'drill', 'acc', 'lib', 'me']);
  assert.deepStrictEqual($$(h, '#tabbar [data-tb] i').map(b => b.textContent),
    ['今日', '练', '积累', '库', '我的']);
});

test('「专项突破」的板块是从 BOARD_FEATURES 反查的，不是另抄一份清单', (t) => {
  const h = boot(); t.after(() => h.close());
  tap(h, 'drill');
  // 真话来源：core.js 里配了 drill 的板块，一个不多一个不少
  const want = h.plain(`Object.keys(BOARD_FEATURES)
    .filter(b => (BOARD_FEATURES[b] || []).some(f => f.key === 'drill'))`);
  assert.ok(want.length >= 5, '前提没了：core.js 里几乎没有板块配 drill');
  const names = $$(h, '#tab-groups .tab-row .tr-n').map(b => b.textContent);
  want.forEach(b => assert.ok(names.includes(b), `专项突破漏了板块「${b}」`));
});

test('条目点下去落到真入口，不是空壳', async (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  tap(h, 'drill');
  const row = $$(h, '#tab-groups .tab-row').find(r => r.querySelector('.tr-n').textContent === '历年真题');
  assert.ok(row, '「练」里没有历年真题');
  row.click();
  assert.strictEqual(h.window.document.body.dataset.view, 'realq');
});

test('标签之间是平级切换：连切三次，栈还是两层，返回一步回首页', (t) => {
  const h = boot(); t.after(() => h.close());
  tap(h, 'drill'); tap(h, 'acc'); tap(h, 'lib');
  assert.strictEqual(h.run('stack.length'), 2, '每切一个标签就多压一层，返回键会按不完');
  assert.strictEqual(h.run('stack[0].view'), 'home');
  h.run('back()');
  assert.strictEqual(h.window.document.body.dataset.view, 'home');
});

test('「今日」回到首页，且返回键跟着消失（首页是栈底，不是又压一层首页）', (t) => {
  const h = boot(); t.after(() => h.close());
  tap(h, 'acc');
  tap(h, 'today');
  assert.strictEqual(h.run('stack.length'), 1);
  assert.strictEqual(h.window.document.body.dataset.view, 'home');
  assert.ok($(h, '#nav-back').classList.contains('hidden'), '回到首页了返回键还亮着');
});

test('进到二级页，底下亮的还是它所属的标签', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  tap(h, 'acc');
  const row = $$(h, '#tab-groups .tab-row').find(r => r.querySelector('.tr-n').textContent === '成语词语积累');
  assert.ok(row, '「积累」里没有成语词语积累');
  row.click();
  assert.strictEqual(h.window.document.body.dataset.view, 'idiom');
  const on = $$(h, '#tabbar [data-tb].on').map(b => b.dataset.tb);
  assert.deepStrictEqual(on, ['acc'], '一进二级页标签就全灭了');
});

test('沉浸式页面让位：做题页和小记不出标签栏，页面底部也不留那条空白', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  const body = h.window.document.body;
  tap(h, 'drill');
  assert.ok(body.classList.contains('has-tabs'), '标签页里反而没有标签栏');

  // 做题：整屏专注，答题区不能被横条切掉
  h.run("push({ view: 'realrun' })");
  assert.ok($(h, '#tabbar').classList.contains('hidden'), '做题页还压着标签栏');
  assert.ok(!body.classList.contains('has-tabs'), '--tabh 没撤，页面底下白留一条');

  // 小记：屏幕底下已经住着 .notes-pill（搜索 / + / AI），两条栏叠一起没法按
  h.run("push({ view: 'notes' })");
  assert.ok($(h, '#tabbar').classList.contains('hidden'), '标签栏压在小记悬浮条上');

  h.run('back(); back()');
  assert.ok(body.classList.contains('has-tabs'), '退回标签页后标签栏没回来');
});

test('顶栏那三个按钮在手机端交给标签栏，样式里得真收掉', () => {
  // 「首页」→ 今日标签，「账户」「后台」→ 我的。留着就是两套导航并存，顶栏还占一行。
  // 这条盯的是 CSS：JS 里它们照旧存在（电脑端还要用），只在手机断点下隐藏。
  const css = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/style.css'), 'utf8');
  const m = css.match(/@media\(max-width:760px\)\{[^}]*#home-btn[^}]*\}/);
  assert.ok(m, '手机断点里没把 #home-btn / #account-btn / #admin-btn 收掉');
  ['#account-btn', '#admin-btn'].forEach(id => assert.ok(m[0].includes(id), '漏了 ' + id));
});

test('管理后台只给管理员看', (t) => {
  const h = boot(); t.after(() => h.close());
  tap(h, 'me');
  const names = () => $$(h, '#tab-groups .tab-row .tr-n').map(b => b.textContent);
  assert.ok(!names().includes('管理后台'), '非管理员也看得到后台入口');

  h.run("ME = { is_admin: true }");
  tap(h, 'me');
  assert.ok(names().includes('管理后台'), '管理员反而看不到后台入口');
});

test('分组标题和条目名走转义（板块名来自接口，将来可能是用户自定义的）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`SECTIONS = [{ key: 'x', name: '<img src=x onerror=alert(1)>行测', desc: '<b>y</b>', boards: [] }]`);
  tap(h, 'drill');
  const box = $(h, '#tab-groups');
  assert.strictEqual(box.querySelector('img'), null, '板块名里的 img 活了');
  assert.match(box.textContent, /<img src=x/);
  /* 一箭双雕：描述里注入的 <b>y</b> 要是没转义就会在这儿变成真标签。
     而本模块自己**一个 <b> 都不该产出** —— 夜间有条全局的
     body.dark b{color:#f0c674!important}，标题用 <b> 会整片变金。 */
  assert.strictEqual(box.querySelector('b'), null, '描述里的 b 活了，或者标题又用回了 <b>');
});

/* 做题页答题卡 + 键盘快捷键（界面重构 P4）。
 *
 * 答题卡补的是**一个真缺口**，不只是排版：真题做题页原来只有「下一题」，
 * 整卷 130 道想回头改第 47 题只能交卷重来。所以第一组测试盯「跳得回去」。
 *
 * 最要命的一条是**模考模式下不能透出对错**：答题卡若按对错上色，等于提前判卷，
 * 整个模考就废了。这条不会抛异常、界面也不会出错，只会静默地把功能变质。
 *
 * 键盘那组盯两件事：在输入框里打字时一个键都不许拦（做题页有随手记、有搜索），
 * 以及只在做题页生效——别的页面按 j 应该什么都不发生。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const $ = (h, s) => h.window.document.querySelector(s);
const $$ = (h, s) => [...h.window.document.querySelectorAll(s)];

function sheet(h, o) {
  h.window.__jump = [];
  h.run(`qsRender('#rq-side', {
    n: ${o.n}, cur: ${o.cur},
    state: (i) => (${JSON.stringify(o.state || {})})[i] || '',
    onJump: (i) => window.__jump.push(i),
  })`);
}
const cells = (h) => $$(h, '#rq-side .qs-c');

test('每题一格，当前那格标出来', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 5, cur: 2 });
  assert.strictEqual(cells(h).length, 5);
  assert.deepStrictEqual(cells(h).map(c => c.textContent), ['1', '2', '3', '4', '5']);
  assert.deepStrictEqual(cells(h).filter(c => c.classList.contains('qs-cur')).map(c => c.textContent), ['3']);
});

test('点一格就跳过去 —— 这才是加它的理由', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 20, cur: 19 });
  cells(h)[3].click();
  assert.deepStrictEqual(h.window.__jump, [3], '点了第 4 格没跳过去，整卷就还是只能一路向前');
});

test('已答/未答一眼看得出，标题上报「答了几道」', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 4, cur: 0, state: { 0: 'right', 1: 'wrong', 2: 'done' } });
  const c = cells(h);
  assert.ok(c[0].classList.contains('qs-right'));
  assert.ok(c[1].classList.contains('qs-wrong'));
  assert.ok(c[2].classList.contains('qs-done'));
  assert.ok(!/qs-(right|wrong|done)/.test(c[3].className), '没答的格子不该带状态');
  assert.strictEqual($(h, '#rq-side .qs-n').textContent, '3/4');
});

test('模考模式只报「答过没答过」，绝不能透出对错', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  // 直接驱动真题模块：这一条测的是 realq.js 给答题卡喂了什么，不是答题卡自己
  h.run(`rqExam = true; rqIdx = 0;
    rqItems = [{ id: 1, answer: 'A', options: ['x','y','z','w'], stem: 's' },
               { id: 2, answer: 'B', options: ['x','y','z','w'], stem: 's' }];
    rqAns = { 1: 'A', 2: 'D' };
    rqRender();`);
  const cls = cells(h).map(c => c.className);
  assert.ok(cls.every(c => !/qs-right|qs-wrong/.test(c)),
    '模考模式下答题卡按对错上色了 —— 等于提前判卷，模考就白做了');
  assert.ok(cls.every(c => /qs-done/.test(c)), '答过的题也该看得出来');
});

test('背题模式才按对错上色', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run(`rqExam = false; rqIdx = 0;
    rqItems = [{ id: 1, answer: 'A', options: ['x','y','z','w'], stem: 's' },
               { id: 2, answer: 'B', options: ['x','y','z','w'], stem: 's' }];
    rqAns = { 1: 'A', 2: 'D' };
    rqRender();`);
  const c = cells(h);
  assert.ok(c[0].classList.contains('qs-right'));
  assert.ok(c[1].classList.contains('qs-wrong'));
});

test('题目没了就把答题卡收掉，不留一张空卡', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 3, cur: 0 });
  h.run("qsRender('#rq-side', { n: 0 })");
  assert.strictEqual($(h, '#rq-side').innerHTML, '');
});

/* ---------------- 键盘 ---------------- */
function key(h, k, target) {
  const ev = new h.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
  (target || h.window.document.body).dispatchEvent(ev);
  return ev;
}

test('做题页按 A–D 直接选选项', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run(`rqExam = false; rqIdx = 0;
    rqItems = [{ id: 1, answer: 'C', options: ['甲','乙','丙','丁'], stem: 's' }];
    rqAns = {}; rqSec = {}; rqRender();`);
  h.window.document.body.dataset.view = 'realrun';
  key(h, 'c');
  assert.strictEqual(h.plain('rqAns[1]'), 'C', '按 c 没选中 C 选项');
});

test('在输入框里打字时一个键都不拦', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  h.run(`rqExam = false; rqIdx = 0;
    rqItems = [{ id: 1, answer: 'C', options: ['甲','乙','丙','丁'], stem: 's' }];
    rqAns = {}; rqSec = {}; rqRender();`);
  h.window.document.body.dataset.view = 'realrun';
  const ta = h.window.document.createElement('textarea');
  h.window.document.body.appendChild(ta);
  ta.focus();
  const ev = key(h, 'c', ta);
  assert.strictEqual(ev.defaultPrevented, false, '在输入框里打「c」被当成了选 C');
  assert.strictEqual(h.plain('Object.keys(rqAns).length'), 0);
});

test('J / K 借答题卡切上下题', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 5, cur: 2 });
  h.window.document.body.dataset.view = 'realrun';
  key(h, 'j');
  key(h, 'k');
  assert.deepStrictEqual(h.window.__jump, [3, 1], 'J 该往后一题、K 该往前一题');
});

test('到头了不乱跳，也不吞掉按键', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 3, cur: 0 });
  h.window.document.body.dataset.view = 'realrun';
  const ev = key(h, 'k');
  assert.deepStrictEqual(h.window.__jump, [], '第一题按 K 还往前跳');
  assert.strictEqual(ev.defaultPrevented, false, '没跳成还把按键吞了');
});

test('只在做题页生效：别的页面按 j 什么都不该发生', (t) => {
  const h = boot(); t.after(() => h.close());
  sheet(h, { n: 5, cur: 2 });
  h.window.document.body.dataset.view = 'notes';
  key(h, 'j');
  assert.deepStrictEqual(h.window.__jump, [], '小记页面按 j 也去翻题了');
});

/* ---------------- 回归：审查抓到的四条 ---------------- */

test('两张答题卡同时在 DOM 里时，J/K 只认当前视图那一张', (t) => {
  const h = boot(); t.after(() => h.close());
  const doc = h.window.document;
  // 真题的卡先渲染（它在 DOM 里排在前面），然后切到专项练
  h.window.__jump = [];
  h.run(`qsRender('#rq-side', { n: 20, cur: 5, state: () => '', onJump: (i) => window.__jump.push('rq:' + i) })`);
  h.run(`qsRender('#dr-side', { n: 8, cur: 2, state: () => '', onJump: (i) => window.__jump.push('dr:' + i) })`);
  doc.body.dataset.view = 'drillrun';
  key(h, 'j');
  assert.deepStrictEqual(h.window.__jump, ['dr:3'],
    '在专项练里按 J，驱动的却是真题那张卡 —— 题号不动，两边的计时器一起被搅乱');
});

test('专项练交卷后答题卡要真撤掉，不是只藏起来', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`qsRender('#dr-side', { n: 5, cur: 1, state: () => '', onJump: () => {} })`);
  h.run("qsClear('#dr-side')");
  assert.strictEqual($$(h, '#dr-side .qs-c').length, 0,
    '格子还留在 DOM 里：键盘照样查得到、点得动，交卷后按 j 会跳回题目');
  assert.ok($(h, '#dr-side').classList.contains('hidden'));
});

test('背题模式不能捡上一局测试模式留下的旧答题卡', (t) => {
  const h = boot({ fetch: () => ({ json: {} }) }); t.after(() => h.close());
  // 先来一局 8 题的测试模式，卡留在那儿
  h.run(`qsRender('#dr-side', { n: 8, cur: 0, state: () => '', onJump: () => {} })`);
  // 再开一局 3 题的背题模式：drRender 走 else 分支
  h.run(`drMode = 'study'; drItems = [{ q: 'a', options: ['1','2','3','4'] },
    { q: 'b', options: ['1','2','3','4'] }, { q: 'c', options: ['1','2','3','4'] }];
    drAns = []; drSec = []; drIdx = 0; drLevel = 'easy'; drRender();`);
  assert.strictEqual($$(h, '#dr-side .qs-c').length, 0,
    '旧卡还有 8 格：按 j 能把 drIdx 推过 3 题，drRender 当场判成交卷');
});

test('真题交卷后答题卡要撤掉，不然点一下就把题目盖回成绩上', async (t) => {
  const h = boot({
    fetch: (url) => url.startsWith('/api/real/done')
      ? { json: { results: [], score: 1, total: 2 } } : { json: {} },
  });
  t.after(() => h.close());
  // 错题扫描是交卷后自己跑的一条尾巴，会活过测试结束、在窗口关掉之后才炸。
  // 它和这条测的事无关，桩掉。
  h.run('rqScanWq = () => Promise.resolve()');
  await h.run(`(async () => {
    rqExam = true; rqIdx = 0; rqDone = false;
    rqItems = [{ id: 1, answer: 'A', options: ['x','y','z','w'], stem: 's' },
               { id: 2, answer: 'B', options: ['x','y','z','w'], stem: 's' }];
    rqAns = { 1: 'A' }; rqSec = {}; rqRender();
    await rqFinish();
  })()`);
  await new Promise(r => setTimeout(r, 20));
  assert.strictEqual($$(h, '#rq-side .qs-c').length, 0,
    '成绩页上还留着答题卡：点一格就重画题目盖住成绩，而且再也交不了卷（rqDone 拦着）');
});

test('做题页的两栏布局不能挂在 body.has-tabs 上', () => {
  // 做题页在 TAB_OFF 里（整屏专注），has-tabs 恰恰在这两个视图上被摘掉，
  // 挂上去等于这套布局永远不生效——答题卡掉下来变成通栏一大块，还看不出哪儿错了。
  const css = require('fs').readFileSync(
    require('path').join(__dirname, '../../static/style.css'), 'utf8');
  assert.ok(/\n  #view-realrun,#view-drillrun\{\s*display:grid/.test(css),
    '两栏布局的选择器没有独立出来');
  assert.ok(!/body\.has-tabs #view-(realrun|drillrun)/.test(css),
    '两栏布局还挂着 body.has-tabs —— 做题页上这个类是不存在的');
});

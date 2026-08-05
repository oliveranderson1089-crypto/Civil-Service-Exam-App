/* 今日仪表盘（界面重构 P1）。
 *
 * 这一屏的失败模式不是「报错」，是**报喜不报忧**：没数据时糊一堆 0 和一个满环，
 * 看着像在学习，实际什么都没发生。所以下面大半的测试都在盯「空的时候说了什么」：
 *
 *   · 没排任务 → 不许拿 0%／100% 冒充完成度，要给「去排今天的任务」；
 *   · 今天没有新内容 → 要明说「还没有新内容进来」。素材/时政是后台 cron 产出的，
 *     断供过而且是**无声的**；首页要是显示成一切正常，断供能瞒好几天；
 *   · 「上次练习」不叫「接着做」—— 库里根本没有「做到一半」这个状态，
 *     只有交卷后的整组记录，写成「接着做」就是骗人。
 *
 * 另外两条是结构：主行动只能有一个（两个并列的大按钮 = 没有主次，又回到让用户自己挑），
 * 以及聚合接口挂了要能重试、不能白屏。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const BASE = {
  date: '2026-08-05', weekday: '周三', exam: null,
  streak: 0, study_days: 0,
  done: { questions: 0, correct: 0, minutes: 0 },
  dtest: { has: false, runs: 0, score: 0, total: 0 },
  tasks: { done: 0, total: 0 }, plan: { done: 0, total: 0 },
  updates: [], last: null,
};

// 只覆盖要测的那几个字段，其余用 BASE
function bootToday(over, review) {
  const d = Object.assign({}, BASE, over || {});
  return boot({
    fetch: (url) => url.startsWith('/api/today') ? { json: d }
      : url.startsWith('/api/review/today') ? { json: { count: review || 0 } }
        : { json: {} },
  });
}
const body = (h) => h.window.document.getElementById('today-body');
const txt = (h) => body(h).textContent;

test('没排任务就不给完成度：不显示 0%，而是给下一步动作', async (t) => {
  const h = bootToday(); t.after(() => h.close());
  await h.run('tdLoad(true)');
  const ring = body(h).querySelector('.td-ring');
  assert.ok(ring.classList.contains('td-ring-off'), '没任务却画了一个真的完成度环');
  assert.ok(!/\d+%/.test(ring.textContent), '拿 0% 冒充了完成度：' + ring.textContent);
  assert.match(txt(h), /今天还没安排任务/);
  assert.ok(body(h).querySelector('[data-td="tasks"]'), '没给「去排今天的任务」的入口');
});

test('完成度把任务清单和今日计划合起来算', async (t) => {
  const h = bootToday({ tasks: { done: 1, total: 3 }, plan: { done: 2, total: 2 } });
  t.after(() => h.close());
  await h.run('tdLoad(true)');
  const ring = body(h).querySelector('.td-ring');
  assert.strictEqual(ring.textContent.trim(), '60%', '3/5 该是 60%');
  assert.match(txt(h), /今日任务 3\/5 项/);
});

test('主行动只有一个：没做巩固测试就催它，做过了换成练真题', async (t) => {
  const h1 = bootToday({ dtest: { has: true, runs: 0, score: 0, total: 10 } });
  t.after(() => h1.close());
  await h1.run('tdLoad(true)');
  let cta = body(h1).querySelectorAll('.td-cta');
  assert.strictEqual(cta.length, 1, '并列了多个大按钮，等于没有主次');
  assert.strictEqual(cta[0].dataset.td, 'dtest');
  assert.match(cta[0].textContent, /开始今天的学习/);

  const h2 = bootToday({ dtest: { has: true, runs: 1, score: 8, total: 10 } });
  t.after(() => h2.close());
  await h2.run('tdLoad(true)');
  cta = body(h2).querySelectorAll('.td-cta');
  assert.strictEqual(cta.length, 1);
  assert.strictEqual(cta[0].dataset.td, 'realq', '测试做完了还在催做测试');
  assert.match(cta[0].textContent, /8\/10/);
});

test('主行动点下去落到真入口', async (t) => {
  const h = bootToday({ dtest: { has: true, runs: 0, score: 0, total: 10 } });
  t.after(() => h.close());
  await h.run('tdLoad(true)');
  // 换掉真的 openDtest 只观察「有没有调到它」：真跑会拖进整个巩固测试的加载链，
  // 那些异步会活过测试结束、在窗口关掉之后才炸，测的还不是这一屏的事
  h.run("openDtest = () => { window.__hit = 'dtest'; }");
  body(h).querySelector('.td-cta').click();
  assert.strictEqual(h.window.__hit, 'dtest');
});

test('今天没有新内容就明说，不假装一切正常', async (t) => {
  const h = bootToday(); t.after(() => h.close());
  await h.run('tdLoad(true)');
  // 素材/时政断供过，而且是无声的。首页显示「都齐了」的话，断供能瞒好几天
  assert.match(txt(h), /今天还没有新内容进来/);
  assert.strictEqual(body(h).querySelector('.td-up'), null);
});

test('有更新时按来源分格，点进去是对应的功能', async (t) => {
  const h = bootToday({ updates: [{ go: 'sucai', name: '素材积累', n: 4 }] });
  t.after(() => h.close());
  await h.run('tdLoad(true)');
  const up = body(h).querySelector('.td-up');
  assert.match(up.textContent, /素材积累/);
  assert.match(up.textContent, /\+4 条/);
  h.run("openSucai = (k) => { window.__hit = 'sucai:' + k; }");
  up.click();
  assert.strictEqual(h.window.__hit, 'sucai:全部');
});

test('复习条数来自 /api/review/today；它挂了也不该拖垮整屏', async (t) => {
  const h = bootToday({}, 12); t.after(() => h.close());
  await h.run('tdLoad(true)');
  const row = body(h).querySelector('[data-td="review"]');
  assert.ok(row, '有 12 条要复习却没出现在待办里');
  assert.match(row.textContent, /12/);

  // 复习接口挂了：仪表盘其余部分照常出来
  const h2 = boot({
    fetch: (url) => url.startsWith('/api/today') ? { json: BASE }
      : url.startsWith('/api/review/today') ? new Error('炸了') : { json: {} },
  });
  t.after(() => h2.close());
  await h2.run('tdLoad(true)');
  assert.ok(body(h2).querySelector('.td-cta'), '复习那条挂了就把整屏拖没了');
});

test('聚合接口挂了给的是错误和重试，不是白屏', async (t) => {
  const h = boot({ fetch: () => new Error('后端 502') }); t.after(() => h.close());
  await h.run('tdLoad(true)');
  assert.match(txt(h), /502/);
  assert.ok(body(h).querySelector('[data-td="retry"]'), '没给重试按钮，用户只能杀进程');
});

test('叫「上次练习」不叫「接着做」：库里没有做到一半这个状态', async (t) => {
  const h = bootToday({ last: { go: 'realq', scope: '2024 国考 · 资料分析', total: 20, correct: 17 } });
  t.after(() => h.close());
  await h.run('tdLoad(true)');
  assert.match(txt(h), /上次练习/);
  assert.ok(!/接着做|继续做/.test(txt(h)), '写成了「接着做」，但库里根本没存断点');
  assert.match(txt(h), /17\/20 · 85%/);
});

test('接口回来的文本走转义', async (t) => {
  const h = bootToday({
    last: { go: 'realq', scope: '<img src=x onerror=alert(1)>卷', total: 1, correct: 1 },
    updates: [{ go: 'news', name: '<b>时政</b>', n: 1 }],
  });
  t.after(() => h.close());
  await h.run('tdLoad(true)');
  assert.strictEqual(body(h).querySelector('img'), null, 'scope 里的 img 活了');
  assert.strictEqual(body(h).querySelector('b'), null, '来源名里的 b 活了');
  assert.match(txt(h), /<img src=x/);
});

test('原来的九宫格没丢：还在 #home-cards，从「我的 › 全部功能」进得去', async (t) => {
  const h = bootToday(); t.after(() => h.close());
  const doc = h.window.document;
  const grid = doc.getElementById('home-cards');
  assert.ok(grid, '#home-cards 整个没了，AI 工具面板和拖拽排序都要跟着废');
  assert.strictEqual(grid.closest('.view').id, 'view-allfeats', '九宫格没挪进「全部功能」页');

  h.run("ME = { is_admin: false }");
  doc.querySelector('#tabbar [data-tb="me"]').click();
  const row = [...doc.querySelectorAll('#tab-groups .tr-n')].find(b => b.textContent === '全部功能');
  assert.ok(row, '「我的」里没有「全部功能」入口，老九宫格就成了孤儿页');
  row.closest('.tab-row').click();
  assert.strictEqual(doc.body.dataset.view, 'allfeats');
});

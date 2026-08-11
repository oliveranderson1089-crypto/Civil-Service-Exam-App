/* 「库」和「我的」的首屏（界面重构 P4）。
 *
 * 这两页换了形态（图标格 + 最近打开 / 完成度环 + 紧凑清单），最容易丢的是**入口**：
 * 原来一列目录条里的东西，改版时少放一个不会报错，只会从此点不到。
 * 所以下面第一组测试就是「九个入口一个不少、点下去落到真视图」。
 *
 * 第二类是这两页特有的：它们要拉接口。接口挂了必须**照样能点** ——
 * 库的六个格子和我的九个入口都是纯导航，为几个数字把整页变成「加载失败」是本末倒置。
 *
 * 第三类沿用首页那条规矩：不许报喜不报忧。本周没排计划就得说「本周还没有计划」，
 * 不许拿 0% 冒充一个完成度。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

const LIB = {
  counts: { note: 3, kb: 1, draft: 0, material: 7, drive: 12, star: 2 },
  recent: [{ kind: 'kbdoc', label: '知识库', id: 5, title: '2026 省考备考大纲', at: '2026-08-05 10:00:00' },
           { kind: 'note', label: '小记', id: 9, title: '言语 · 逻辑填空错因梳理', at: '2026-08-04 21:00:00' }],
};
const ME = {
  week: { from: '2026-08-03', to: '2026-08-09', done: 6, total: 8, pct: 74 },
  questions: 120, minutes: 95,
  tasks: { done: 1, total: 3 },
  study: { streak: 4, total: 30 },
  unread: { notify: 2, chat: 5 },
};

// 两个标签页各拉各的聚合接口，别的请求（/api/hub 等）一律给空对象
function bootTab(over) {
  const map = Object.assign({ '/api/lib/home': LIB, '/api/me/home': ME }, over || {});
  return boot({ fetch: (url) => ({ json: map[url.split('?')[0]] || {} }) });
}
const $ = (h, sel) => h.window.document.querySelector(sel);
const $$ = (h, sel) => [...h.window.document.querySelectorAll(sel)];
const tap = (h, key) => $(h, `#tabbar [data-tb="${key}"]`).click();
// 骨架是同步画的，数字要等一次 await —— 让微任务跑完再断言
const settle = () => new Promise(r => setTimeout(r, 0));

test('库：六个容器一个不少，点下去落到真视图', async (t) => {
  const h = bootTab(); t.after(() => h.close());
  tap(h, 'lib');
  const names = $$(h, '#tab-groups .lb-tile .lb-n').map(b => b.textContent);
  assert.deepStrictEqual(names, ['小记', '知识库', '草稿本', '资料库', '云盘', '收藏']);
  $$(h, '#tab-groups .lb-tile')[4].click();       // 云盘
  assert.strictEqual(h.window.document.body.dataset.view, 'drive');
  await settle();      // 云盘自己的加载还在跑，等它跑完再关窗口
});

test('库：数字回来了填在格子上，最近打开按接口给的次序摆', async (t) => {
  const h = bootTab(); t.after(() => h.close());
  tap(h, 'lib');
  await settle();
  const box = $(h, '#tab-groups');
  assert.match(box.querySelector('.lb-tile .lb-c').textContent, /3 条/);
  assert.deepStrictEqual($$(h, '#tab-groups .tv-row .tv-name').map(b => b.textContent),
    ['2026 省考备考大纲', '言语 · 逻辑填空错因梳理']);
  assert.deepStrictEqual($$(h, '#tab-groups .tv-row .tv-tag').map(b => b.textContent),
    ['知识库', '小记']);
});

test('库：接口挂了照样能进各个库（导航不该给数字陪葬）', async (t) => {
  const h = boot({ fetch: (url) => url.startsWith('/api/lib/home') ? new Error('500') : { json: {} } });
  t.after(() => h.close());
  tap(h, 'lib');
  await settle();
  assert.strictEqual($$(h, '#tab-groups .lb-tile').length, 6);
  $$(h, '#tab-groups .lb-tile')[3].click();       // 资料库
  assert.strictEqual(h.window.document.body.dataset.view, 'materials');
  await settle();
});

test('库：空库就说空，不藏起来也不糊假数据', async (t) => {
  const h = bootTab({ '/api/lib/home': { counts: {}, recent: [] } }); t.after(() => h.close());
  tap(h, 'lib');
  await settle();
  assert.match($(h, '#tab-groups').textContent, /最近打开[\s\S]*库里还没有东西/);
  assert.strictEqual($$(h, '#tab-groups .tv-row').length, 0);
});

test('库：最近打开的标题走转义（内容是用户自己写的）', async (t) => {
  const h = bootTab({ '/api/lib/home': { counts: {},
    recent: [{ kind: 'note', label: '小记', id: 1, title: '<img src=x onerror=alert(1)>', at: '2026-08-05' }] } });
  t.after(() => h.close());
  tap(h, 'lib');
  await settle();
  assert.strictEqual($(h, '#tab-groups img'), null, '小记标题里的 img 活了');
  assert.match($(h, '#tab-groups').textContent, /<img src=x/);
});

test('我的：九个入口一个不少（管理后台按身份出现）', async (t) => {
  const h = bootTab(); t.after(() => h.close());
  h.run('ME = { is_admin: true }');
  tap(h, 'me');
  const names = $$(h, '#tab-groups .tv-row .tv-name').map(b => b.textContent);
  assert.deepStrictEqual(names,
    ['任务清单', '计划记录', '今日复习', '全国考情', '聊天', '消息', '全部功能', '账户与外观', '管理后台']);
});

test('我的：本周完成度来自接口，未读数挂在对应的行上', async (t) => {
  const h = bootTab(); t.after(() => h.close());
  tap(h, 'me');
  await settle();
  const ring = $(h, '#tab-groups .td-ring');
  assert.strictEqual(ring.style.getPropertyValue('--p'), '74');
  assert.match($(h, '#tab-groups').textContent, /本周计划完成度 6 \/ 8 项/);
  const row = $$(h, '#tab-groups .tv-row').find(r => r.querySelector('.tv-name').textContent === '聊天');
  assert.strictEqual(row.querySelector('.td-badge').textContent, '5');
});

test('我的：本周没排计划不给 0%，明说还没有计划', async (t) => {
  const h = bootTab({ '/api/me/home': Object.assign({}, ME,
    { week: { from: '2026-08-03', to: '2026-08-09', done: 0, total: 0, pct: null } }) });
  t.after(() => h.close());
  tap(h, 'me');
  await settle();
  assert.ok($(h, '#tab-groups .td-ring').classList.contains('td-ring-off'), '空环画成了实心');
  assert.match($(h, '#tab-groups').textContent, /本周还没有计划/);
  assert.doesNotMatch($(h, '#tab-groups').textContent, /0%/);
});

test('我的：完成度那张卡点了去计划记录', async (t) => {
  const h = bootTab(); t.after(() => h.close());
  tap(h, 'me');
  await settle();
  $(h, '#tab-groups .td-hero').click();
  assert.strictEqual(h.window.document.body.dataset.view, 'planlog');
  await settle();
});

test('收藏：六个模块的星标并成一张单子，点了回到它所在的模块', async (t) => {
  const h = bootTab({ '/api/lib/stars': { items: [
    { kind: 'ck', label: '词语', title: '统筹兼顾', sub: '上位词', ref: '上位词', at: '2026-08-05' },
    { kind: 'classic', label: '古诗文', title: '将进酒', sub: '李白', ref: '12', at: '2026-08-04' },
  ] } });
  t.after(() => h.close());
  tap(h, 'lib');
  await settle();
  $$(h, '#tab-groups .lb-tile')[5].click();        // 收藏
  await settle();
  assert.strictEqual(h.window.document.body.dataset.view, 'stars');
  assert.deepStrictEqual($$(h, '#st-list .tv-name').map(b => b.textContent), ['统筹兼顾', '将进酒']);
  $$(h, '#st-list .tv-row')[0].click();
  await settle();                                  // openCkBoard 先拉星标再 push
  assert.strictEqual(h.window.document.body.dataset.view, 'ckboard');
  await settle();
});

test('收藏：一条都没有就说空，不留一张白页', async (t) => {
  const h = bootTab({ '/api/lib/stars': { items: [] } }); t.after(() => h.close());
  h.run('openStars()');
  await settle();
  assert.match($(h, '#st-list').textContent, /还没有收藏/);
  assert.strictEqual($(h, '#st-chips').innerHTML, '', '一条收藏都没有还摆了筛选条');
});

/* 加载态：原来是一块矮矮的「加载中…」，数据一到整页往下窜一截 —— 看到的就是"闪一下"。
   骨架的全部意义就是把这一跳消掉，所以测的是**占位块和真内容行数一致**，
   以及页面上不再出现"加载中"这三个字（有它就说明又退回去了）。 */
test('库：数据没回来时摆骨架，不是一块「加载中…」', (t) => {
  const h = bootTab(); t.after(() => h.close());
  tap(h, 'lib');                                   // 不 await：这一拍就是加载中的样子
  const box = $(h, '#tab-groups');
  assert.ok(box.querySelectorAll('.tv-sk').length >= 3, '加载态一个占位块都没有');
  assert.strictEqual($$(h, '#tab-groups .tv-rows .tv-row').length, 3, '骨架行数和真列表对不上');
  assert.doesNotMatch(box.textContent, /加载中/);
});

test('我的：环卡加载时也占住位置（骨架有宽度，不是塌成一条线）', (t) => {
  const h = bootTab(); t.after(() => h.close());
  tap(h, 'me');
  const hero = $(h, '#tab-groups .td-hero');
  assert.ok(hero.querySelector('.sk-ring'), '环的位置没占住');
  // 这一列平时被文字撑开，骨架里没有文字：不给 flex 就是 0 宽，三条灰条会整个消失
  assert.ok(hero.querySelector('.td-hero-t').classList.contains('sk-col'), '文字列没给 sk-col，百分比宽度会塌成 0');
});

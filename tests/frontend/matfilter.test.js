/* 资料库分类栏：外面只占一行，其余收进「更多」面板。
 *
 * 这条栏原先是「8 个固定板块 + 全部自建分类」一次性平铺，越用越长（手机上得横着划）。
 * 改成和小记标签栏一套办法之后，有三条规矩是靠肉眼看不住的，钉在这儿：
 *   · 一份资料都没有的分类不摆在外面（点了必然空，纯噪音）——但要留在面板里，上传时要选；
 *   · 正在筛的那个一定摆在外面，哪怕它 0 份（刚建的空分类就是这种）；
 *   · 顺序照服务端给的用，前端不许自己再排一次。
 * 跑：node --test tests/frontend/matfilter.test.js
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

// 服务端给的顺序：用得多的在前，0 份的沉底（mods/materials.py 的 material_boards）
const ITEMS = [
  { board: 'AI 学习问答', n: 18, custom: true },
  { board: '议论文', n: 8, custom: false },
  { board: '政治理论', n: 8, custom: false },
  { board: '言语理解与表达', n: 6, custom: false },
  { board: '基础综合复习', n: 6, custom: true },
  { board: '判断推理', n: 4, custom: false },
  { board: '每周时政', n: 1, custom: true },
  { board: '常识判断', n: 1, custom: false },
  { board: '资料分析', n: 0, custom: false },
  { board: '数量关系', n: 0, custom: false },
  { board: '应用文', n: 0, custom: false },
];

function bootMat(items = ITEMS) {
  const h = boot({ fetch: (url) => (url.includes('/api/materials/boards') ? { json: { items } } : { json: {} }) });
  h.run('matBoardsAll = ' + JSON.stringify(items) + '; renderMatFilter()');
  return h;
}
// 外面那一行（面板里的不算）
const outer = (h) => [...h.window.document.querySelectorAll('#mat-filter > .tagchip')]
  .map(b => b.textContent.replace(/\d+$/, '').trim());
const panel = (h) => [...h.window.document.querySelectorAll('#mat-filter .tagpanel-list .tagchip')]
  .map(b => b.textContent.replace(/\d+$/, '').trim());

test('外面只摆有资料的分类，0 份的沉进「更多」', (t) => {
  const h = bootMat(); t.after(() => h.close());
  const out = outer(h);
  assert.ok(!out.includes('数量关系'), '一份资料都没有的板块占了外面的位置');
  assert.ok(!out.includes('资料分析'));
  assert.ok(out.includes('AI 学习问答'), '用得最多的没摆出来');
});

test('外面正好一行：全部 + 6 个常用 + 更多', (t) => {
  const h = bootMat(); t.after(() => h.close());
  const out = outer(h);
  assert.strictEqual(out.length, 8, '外面的按钮数变了：' + out.join(' / '));
  assert.strictEqual(out[0], '全部');
  assert.match(out[7], /^更多 5/, '「更多」数不对（11 个分类摆了 6 个，该剩 5）');
});

test('顺序照服务端给的，前端不再排一次', (t) => {
  const h = bootMat(); t.after(() => h.close());
  assert.deepStrictEqual(outer(h).slice(1, 7), ITEMS.slice(0, 6).map(x => x.board));
});

test('正在筛的分类一定摆在外面，哪怕它 0 份', (t) => {
  const h = bootMat(); t.after(() => h.close());
  h.run("matBoard = '数量关系'; renderMatFilter()");
  const out = outer(h);
  assert.ok(out.includes('数量关系'), '筛完之后界面上看不出自己在按哪个分类看');
  assert.strictEqual(out.length, 8, '挤进来时该换掉最后一个，而不是多占一格');
  const on = [...h.window.document.querySelectorAll('#mat-filter > .tagchip.active')].map(b => b.textContent);
  assert.strictEqual(on.length, 1, '高亮的分类不止一个');
});

test('刚建好、还没传东西的分类也摆得出来（服务端还不知道它）', (t) => {
  const h = bootMat(); t.after(() => h.close());
  h.run("matBoard = '晨读'; renderMatFilter()");
  assert.ok(outer(h).includes('晨读'), '新建分类当场就找不着了');
});

test('展开「更多」列出全部分类，搜索能过滤', (t) => {
  const h = bootMat(); t.after(() => h.close());
  h.run('matPanelOpen = true; renderMatFilter()');
  assert.strictEqual(panel(h).length, ITEMS.length, '面板该列全部分类（含 0 份的）');
  assert.ok(h.window.document.querySelector('#mat-filter').classList.contains('mat-open'),
    '容器没换行，面板会被挤在横滚条里');
  h.run("renderMatFilter('时政')");
  assert.deepStrictEqual(panel(h), ['每周时政']);
  // 搜不着的时候，那颗按钮直接变成「新建这个名字」
  h.run("renderMatFilter('晨读')");
  assert.deepStrictEqual(panel(h), []);
  assert.match(h.window.document.querySelector('#mat-newcat').textContent, /新建「晨读」/);
});

test('分类名里的 HTML 当文字，进不了 DOM', (t) => {
  const h = bootMat([{ board: '<img src=x onerror=alert(1)>', n: 3, custom: true }]);
  t.after(() => h.close());
  h.run('matPanelOpen = true; renderMatFilter()');
  const box = h.window.document.querySelector('#mat-filter');
  assert.strictEqual(box.querySelector('img'), null, '分类名里的 img 活了');
  const evil = [...box.querySelectorAll('*')].filter(e => [...e.attributes].some(a => /^on/i.test(a.name)));
  assert.deepStrictEqual(evil.map(e => e.tagName), [], '注入出了事件处理器');
});

/* 板块基础知识：renderBkb。
 *
 * basics 改动 1 次、零测试。renderBkb：AI 整理的知识点有则渲染（mdToHtml，已单独测过）、
 * 无则显示生成按钮；「我的补充」要点逐条渲染，要点内容用户手录，要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('有 AI 整理则渲染，无则显示生成按钮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkbData = { ai: '', points: [] }; renderBkb();`);
  assert.match(h.window.document.querySelector('#bkb-wrap').innerHTML, /生成/, '没 AI 时该显示生成按钮');
  h.run(`bkbData = { ai: '# 已整理', points: [] }; renderBkb();`);
  assert.match(h.window.document.querySelector('#bkb-wrap').innerHTML, /已整理/);
});

test('补充要点里的 HTML 当文字', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkbData = { ai: '', points: [{ id: 1, content: '<img src=x onerror=alert(1)>要点' }] }; renderBkb();`);
  const box = h.window.document.querySelector('#bkb-wrap');
  assert.strictEqual(box.querySelector('img'), null, '要点里的 img 活了');
  assert.match(box.textContent, /要点/);
});

test('没补充要点时显示引导文案，不是空白', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkbData = { ai: '', points: [] }; renderBkb();`);
  assert.match(h.window.document.querySelector('#bkb-wrap').textContent, /还没有补充|写点自己/);
});

/* 树有几层是资料决定的：优路/三色两层（章 → 考点），社区线三层（书 → 章/节 → 考点）。
   写死两层那版把社区线 2590 个考点全藏在了第三层，界面上一个都点不到。 */
test('三层资料的考点要露出来，不能只画到章节为止', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkTree = { meta: {}, title: '重点笔记', nodes: [
    { id: 1, title: '社会工作实务重点笔记', level: 1, parent_id: null, kids: 1, blocks: 0 },
    { id: 2, title: '第一节 接案', level: 2, parent_id: 1, kids: 2, blocks: 0 },
    { id: 3, title: '接案的步骤', level: 3, parent_id: 2, kids: 0, blocks: 2 },
    { id: 4, title: '收集资料的方法', level: 3, parent_id: 2, kids: 0, blocks: 1 }
  ] }; renderBkTree();`);
  const box = h.window.document.querySelector('#bktree-wrap');
  assert.match(box.textContent, /接案的步骤/, '第三层的考点没画出来');
  assert.match(box.textContent, /收集资料的方法/);
  assert.ok(box.querySelector('[data-bknode="3"]'), '考点得能点开');
  assert.ok(box.querySelector('[data-bksweep="2"]'), '章节上该有速览入口');
});

test('两层资料照旧画成章 → 考点，不多长一层', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`bkTree = { meta: {}, title: '优路讲义', nodes: [
    { id: 1, title: '第一章 增长率', level: 1, parent_id: null, kids: 2, blocks: 0 },
    { id: 2, title: '增长量', level: 2, parent_id: 1, kids: 0, blocks: 3 },
    { id: 3, title: '基期量', level: 2, parent_id: 1, kids: 0, blocks: 2 }
  ] }; renderBkTree();`);
  const box = h.window.document.querySelector('#bktree-wrap');
  assert.strictEqual(box.querySelectorAll('.bk-sub').length, 0, '两层资料不该长出中间层');
  assert.ok(box.querySelector('[data-bknode="2"]'));
});

/* 原书那一页给两个入口：文字版（能搜能复制、窄屏不用横拖）和原图（图形推理的图、
   竖式分式只有图救得回来）。两个都得在，少哪个都是退步。 */
test('正文块下面同时给出文字版和原图两个入口', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`document.querySelector('#bknode-wrap').innerHTML =
    bkBlocks([{ kind: 'concept', md: '公共管理是…', page: 2, page_to: 2 }], 11);`);
  const box = h.window.document.querySelector('#bknode-wrap');
  assert.ok(box.querySelector('[data-bktext="11:2:2"]'), '没有文字版入口');
  assert.ok(box.querySelector('[data-bkpage="11:2:2"]'), '没有原图入口');
  assert.match(box.textContent, /原书 P2/);
});

test('跨页的块，两个入口都带上整段页范围', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`document.querySelector('#bknode-wrap').innerHTML =
    bkBlocks([{ kind: 'concept', md: '一道题跨了两页', page: 5, page_to: 6 }], 11);`);
  const box = h.window.document.querySelector('#bknode-wrap');
  assert.ok(box.querySelector('[data-bktext="11:5:6"]'));
  assert.match(box.textContent, /原书 P5-P6/);
});

/* 范文库：话题筛选条 renderEsTopics。
 *
 * essays 改动 1 次、零测试。话题条第一个是「全部」，其余按话题列出；当前选中的话题
 * 高亮。话题名来自数据、既进 data-est 又进按钮文字，都要转义。
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./harness');

test('话题条：全部 + 各话题，当前话题高亮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`esPapers = [{ topic: '基层治理' }, { topic: '乡村振兴' }]; esTopic = '乡村振兴'; renderEsTopics();`);
  const chips = [...h.window.document.querySelectorAll('#es-topics .chip')];
  assert.strictEqual(chips[0].textContent, '全部');
  assert.ok(!chips[0].classList.contains('active'), '选了具体话题，「全部」不该高亮');
  const active = chips.filter(c => c.classList.contains('active'));
  assert.strictEqual(active.length, 1);
  assert.strictEqual(active[0].textContent, '乡村振兴', '高亮的不是当前话题');
});

test('没选话题时「全部」高亮', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`esPapers = [{ topic: 'x' }]; esTopic = ''; renderEsTopics();`);
  const first = h.window.document.querySelector('#es-topics .chip');
  assert.ok(first.classList.contains('active'), '没选话题时「全部」该高亮');
});

test('话题名里的 HTML 当文字（进按钮文字和 data-est 两条路都转义）', (t) => {
  const h = boot(); t.after(() => h.close());
  h.run(`esPapers = [{ topic: '"><img src=x onerror=alert(1)>' }]; esTopic = ''; renderEsTopics();`);
  const box = h.window.document.querySelector('#es-topics');
  assert.strictEqual(box.querySelector('img'), null, '话题名里的 img 活了 —— data-est 属性被闭合');
});
